"""Operator holds and over-cap alerts: block a model/pool for N minutes, warn above 100%."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
from pathlib import Path
import sys
import unittest
import unittest.mock

from fastapi.testclient import TestClient
import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from proxy_gateway.app import create_app
from proxy_gateway.quota_manager import QuotaManager

POLICY = REPO_ROOT / "proxy_gateway" / "quota_policy.yaml"
NOW = datetime(2026, 11, 24, 16, 0, tzinfo=timezone.utc)


class HoldTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.holds = Path(tmp.name) / "holds.json"
        self.qm = QuotaManager(POLICY, Path(tmp.name) / "q.db", holds_path=self.holds)

    def test_hold_blocks_the_model_and_says_for_how_long(self) -> None:
        self.qm.hold("kimi-for-coding", 240, "weekly cap spent", now_utc=NOW)
        sel = self.qm.select_candidates("system_1_5", "openai", "kimi-for-coding", now_utc=NOW, pin_requested=True)
        self.assertNotEqual(sel.model_key, "kimi-for-coding")
        self.assertIn("manual_hold(240m)", sel.skipped_reasons["kimi-for-coding"])

    def test_a_pool_hold_blocks_every_model_in_it(self) -> None:
        self.qm.hold("zhipu_v2_max", 30, now_utc=NOW)
        for model in ("zhipu-glm-5.4", "zhipu-glm-5.3-flash"):
            sel = self.qm.select_candidates("system_1_5", "openai", model, now_utc=NOW, pin_requested=True)
            self.assertNotEqual(sel.model_key, model, model)

    def test_release_and_expiry(self) -> None:
        self.qm.hold("kimi-for-coding", 60, now_utc=NOW)
        self.assertTrue(self.qm.release("kimi-for-coding")["released"])
        free = self.qm.select_candidates("system_1_5", "openai", "kimi-for-coding", now_utc=NOW, pin_requested=True)
        self.assertEqual(free.model_key, "kimi-for-coding")
        self.qm.hold("kimi-for-coding", 1, now_utc=NOW)
        later = NOW + timedelta(minutes=2)
        expired = self.qm.select_candidates("system_1_5", "openai", "kimi-for-coding", now_utc=later, pin_requested=True)
        self.assertEqual(expired.model_key, "kimi-for-coding")

    def test_holds_persist_across_a_restart(self) -> None:
        self.qm.hold("kimi-for-coding", 600, "still blocked", now_utc=NOW)
        reopened = QuotaManager(POLICY, self.holds.parent / "q2.db", holds_path=self.holds)
        self.assertIn("kimi-for-coding", reopened.active_holds(NOW))


class AlertTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.qm = QuotaManager(POLICY, Path(tmp.name) / "q.db")

    def test_over_cap_is_reported_with_the_booster_state(self) -> None:
        self.qm._remote_usage["kimi_allegretto"] = {"percent": {"week": 104.0, "5h": 3.0}, "ts": NOW,
                                                    "booster": {"remaining": 1.0, "active": True}}
        self.assertEqual(self.qm.over_cap_alerts(NOW), ["kimi_allegretto: week 104% over plan (booster active)"])

    def test_under_cap_and_stale_readings_do_not_alert(self) -> None:
        self.qm._remote_usage["kimi_allegretto"] = {"percent": {"week": 99.0}, "ts": NOW}
        self.assertEqual(self.qm.over_cap_alerts(NOW), [])
        self.qm._remote_usage["kimi_allegretto"] = {"percent": {"week": 120.0}, "ts": NOW - timedelta(hours=2)}
        self.assertEqual(self.qm.over_cap_alerts(NOW), [])

    def test_the_response_advertises_the_alert_and_admin_rejects_unknown_targets(self) -> None:
        def upstream(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}], "usage": {}})
        app = create_app(transport=httpx.MockTransport(upstream), quota_manager=self.qm, now_provider=lambda: NOW)
        client = TestClient(app)
        self.qm._remote_usage["kimi_allegretto"] = {"percent": {"week": 104.0}, "ts": NOW}
        resp = client.post("/v1/chat/completions", json={"model": "x", "stream": False,
                                                         "messages": [{"role": "user", "content": "hi"}]})
        self.assertIn("kimi_allegretto: week 104%", resp.headers["x-harness-quota-alert"])

    def test_admin_requires_the_token_and_rejects_unknown_targets(self) -> None:
        def upstream(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}], "usage": {}})
        app = create_app(transport=httpx.MockTransport(upstream), quota_manager=self.qm, now_provider=lambda: NOW)
        client = TestClient(app)
        self.assertEqual(client.post("/admin/hold", json={"target": "kimi-for-coding"}).status_code, 403)
        with unittest.mock.patch.dict(os.environ, {"HARNESS_ADMIN_TOKEN": "t0ken"}):
            headers = {"x-admin-token": "t0ken"}
            ok = client.post("/admin/hold", headers=headers, json={"target": "kimi-for-coding", "minutes": 5})
            self.assertEqual(ok.status_code, 200, ok.text)
            self.assertIn("kimi-for-coding", client.get("/quota").json()["holds"])
            typo = client.post("/admin/hold", headers=headers, json={"target": "kimi-for-codng"})
            self.assertEqual(typo.status_code, 404)  # a typo must not look like success
            self.assertIn("kimi-for-coding", typo.json()["models"])
            released = client.post("/admin/unhold", headers=headers, json={"target": "kimi-for-coding"})
            self.assertTrue(released.json()["released"])


if __name__ == "__main__":
    unittest.main()
