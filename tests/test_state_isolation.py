"""Unit tests must not touch the running gateway's state; a turn that produced nothing is not charged."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

from fastapi.testclient import TestClient
import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import proxy_gateway.app as app_module
from proxy_gateway.app import create_app
from proxy_gateway.quota_manager import QuotaManager

LIVE_STATE = (REPO_ROOT / "traces").resolve()


def _always_429(request: httpx.Request) -> httpx.Response:
    return httpx.Response(429, headers={"retry-after": "90"}, json={"error": {"message": "rate limited"}})


class StateIsolationTests(unittest.TestCase):
    def test_default_state_paths_point_away_from_the_running_gateway(self) -> None:
        # Holds whatever way the suite is imported (package, discover, or this file run directly).
        self.assertNotEqual(app_module.STATE_DIR, LIVE_STATE)
        self.assertIn("harness-test-traces", str(app_module.STATE_DIR))
        for path in (app_module.TRACE_FILE, app_module.DEFAULT_QUOTA_DB, app_module.FAILED_REQUEST_DIR):
            self.assertFalse(LIVE_STATE in path.parents, f"{path} is inside the live traces/ directory")

    def test_a_turn_that_produced_nothing_charges_nothing_to_the_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "q.db"
            qm = QuotaManager(REPO_ROOT / "proxy_gateway" / "quota_policy.yaml", db)
            app = create_app(openai_upstream="https://mock.openai.local/v1", anthropic_upstream="https://mock.anthropic.local",
                             transport=httpx.MockTransport(_always_429), quota_manager=qm,
                             now_provider=lambda: datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc))
            for stream in (True, False):
                resp = TestClient(app).post("/v1/chat/completions", json={
                    "model": "zhipu-glm-5.4", "stream": stream, "messages": [{"role": "user", "content": "hi"}]})
                self.assertEqual(resp.status_code, 503, resp.text)
            # closing(): a transaction context alone keeps the handle open, and Windows then refuses
            # to delete the temporary directory (the commit gate runs the suite on the host).
            with closing(sqlite3.connect(db)) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM pool_usage").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
