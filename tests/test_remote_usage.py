"""Provider-reported usage decides exhaustion for pools that declare a usage endpoint (OpenCode).

2026-11-24: the local ledger read 19.95/20 for OpenCode Go while the provider said 4%; the gateway
skipped it for hours. The limits are percent, the local rows are estimated dollars: different units.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import yaml

from proxy_gateway import quota_manager as qm_mod
from proxy_gateway.quota_manager import REMOTE_USAGE_TTL_SEC, QuotaManager

PAYLOAD = {"usage": {"rolling": {"status": "ok", "percent": 4, "resetsAt": "x"},
                     "weekly": {"status": "ok", "percent": 26}, "monthly": {"status": "ok", "percent": 54}}}
LEAD = "opencode-deepseek-v4.1-flash"


class RemoteUsageTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.now = datetime(2026, 11, 24, 15, 0, tzinfo=timezone.utc)
        self.qm = QuotaManager(REPO_ROOT / "proxy_gateway" / "quota_policy.yaml", Path(tmp.name) / "q.db")

    def test_parses_the_provider_payload(self) -> None:
        self.assertEqual(QuotaManager.parse_usage_payload(PAYLOAD), {"5h": 4.0, "week": 26.0, "month": 54.0})
        self.assertEqual(QuotaManager.parse_usage_payload({"error": "nope"}), {})

    def test_fresh_provider_reading_beats_the_local_estimate(self) -> None:
        self.qm.record_usage(LEAD, units_override=20.0, now_utc=self.now)  # local estimate: exhausted
        self.qm._remote_usage["opencode_go_basic"] = {"percent": {"5h": 4.0, "week": 26.0, "month": 54.0}, "ts": self.now}
        sel = self.qm.select_candidates("system_1_5", "openai", LEAD, now_utc=self.now, pin_requested=True)
        self.assertEqual(sel.model_key, LEAD)

    def test_provider_says_exhausted_is_skipped_and_says_so(self) -> None:
        self.qm._remote_usage["opencode_go_basic"] = {"percent": {"5h": 19.95}, "ts": self.now}
        sel = self.qm.select_candidates("system_1_5", "openai", LEAD, now_utc=self.now, pin_requested=True)
        self.assertNotEqual(sel.model_key, LEAD)
        self.assertIn("5h_exhausted(remote ", sel.skipped_reasons[LEAD])

    def test_stale_reading_falls_back_to_the_local_estimate_and_labels_it(self) -> None:
        self.qm.record_usage(LEAD, units_override=20.0, now_utc=self.now)
        stale = self.now - timedelta(seconds=REMOTE_USAGE_TTL_SEC + 1)
        self.qm._remote_usage["opencode_go_basic"] = {"percent": {"5h": 4.0}, "ts": stale}
        sel = self.qm.select_candidates("system_1_5", "openai", LEAD, now_utc=self.now, pin_requested=True)
        self.assertIn("local-est", sel.skipped_reasons[LEAD])
        snap = self.qm.status_snapshot(self.now)["pools"]["opencode_go_basic"]["remote_usage"]
        self.assertEqual(snap["percent"], {"5h": 4.0})
        self.assertFalse(snap["authoritative"])

    def test_no_network_unless_started_and_pool_config_declares_the_endpoint(self) -> None:
        self.assertIsNone(self.qm._remote_thread)
        policy = yaml.safe_load((REPO_ROOT / "proxy_gateway" / "quota_policy.yaml").read_text(encoding="utf-8"))
        self.assertEqual(policy["pools"]["opencode_go_basic"]["usage_endpoint"], "https://opencode.ai/inference/go/v1/usage")
        self.assertEqual(policy["pools"]["opencode_go_basic"]["unit"], "percent")


if __name__ == "__main__":
    unittest.main()
