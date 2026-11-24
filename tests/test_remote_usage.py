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
ZHIPU = {"code": 200, "data": {"limits": [
    {"type": "TOKENS_LIMIT", "unit": 3, "number": 5, "percentage": 7, "nextResetTime": 1795551987202},
    {"type": "TOKENS_LIMIT", "unit": 6, "number": 1, "percentage": 87, "nextResetTime": 1795841989984},
    {"type": "TIME_LIMIT", "unit": 5, "number": 1, "usage": 4000, "currentValue": 9, "percentage": 1},
]}}
KIMI = {"usage": {"limit": "100", "used": "100", "resetTime": "2026-11-29T09:12:26Z"},
        "limits": [{"window": {"duration": 300, "timeUnit": "TIME_UNIT_MINUTE"},
                    "detail": {"limit": "100", "remaining": "100"}}],
        "booster_wallet": {"status": "STATUS_ACTIVE", "allowTopup": True,
                           "balance": {"amount": "35000000000", "unit": "UNIT_CURRENCY",
                                       "type": "BOOSTER", "feature": "FEATURE_OMNI"}}}
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

    def test_parses_zhipu_and_kimi_shapes(self) -> None:
        # Real payloads captured 2026-11-24.
        self.assertEqual(QuotaManager.parse_usage_zhipu(ZHIPU), {"5h": 7.0, "week": 87.0})
        self.assertEqual(QuotaManager.parse_usage_kimi(KIMI), {"5h": 0.0, "week": 100.0})
        self.assertEqual(QuotaManager.parse_usage_opencode(PAYLOAD), {"5h": 4.0, "week": 26.0, "month": 54.0})
        for fmt in QuotaManager.USAGE_FORMATS:
            self.assertTrue(callable(getattr(QuotaManager, f"parse_usage_{fmt}", None)), fmt)

    def test_kimi_at_its_provider_cap_is_still_tried_and_shows_the_booster(self) -> None:
        # Operator decision: a reading is display data. Boosters raise the plan, and the chain fails over
        # on the provider's own 429, so 100% must not turn into a pre-emptive refusal.
        self.qm._remote_usage["kimi_allegretto"] = {
            "percent": QuotaManager.parse_usage_kimi(KIMI),
            "booster": QuotaManager.parse_booster_kimi(KIMI), "ts": self.now}
        sel = self.qm.select_candidates("system_1_5", "openai", "kimi-for-coding", now_utc=self.now, pin_requested=True)
        self.assertEqual(sel.model_key, "kimi-for-coding")
        remote = self.qm.status_snapshot(self.now)["pools"]["kimi_allegretto"]["remote_usage"]
        self.assertEqual(remote["percent"]["week"], 100.0)
        self.assertEqual(remote["booster"]["remaining"], 35000000000.0)
        self.assertTrue(remote["booster"]["allow_topup"])

    def test_hard_mode_can_still_refuse_a_pool_at_its_cap(self) -> None:
        self.qm.pools["kimi_allegretto"]["remote_exhaustion_mode"] = "hard"
        self.qm._remote_usage["kimi_allegretto"] = {"percent": QuotaManager.parse_usage_kimi(KIMI), "ts": self.now}
        sel = self.qm.select_candidates("system_1_5", "openai", "kimi-for-coding", now_utc=self.now, pin_requested=True)
        self.assertNotEqual(sel.model_key, "kimi-for-coding")
        self.assertIn("week_exhausted(remote", sel.skipped_reasons["kimi-for-coding"])

    def test_a_pool_with_an_endpoint_fails_open_when_the_reading_is_absent(self) -> None:
        # Its limits are percent; the local rows are estimated credits. Comparing them would skip a
        # healthy pool (defect of 2026-11-24), so no fresh reading means no local verdict.
        self.qm.record_usage("zhipu-glm-5.4", units_override=999.0, now_utc=self.now)
        sel = self.qm.select_candidates("system_1_5", "openai", "zhipu-glm-5.4", now_utc=self.now, pin_requested=True)
        self.assertEqual(sel.model_key, "zhipu-glm-5.4")
        self.assertNotIn("zhipu-glm-5.4", sel.skipped_reasons)

    def test_fresh_provider_reading_beats_the_local_estimate(self) -> None:
        self.qm.record_usage(LEAD, units_override=20.0, now_utc=self.now)  # local estimate: exhausted
        self.qm._remote_usage["opencode_go_basic"] = {"percent": {"5h": 4.0, "week": 26.0, "month": 54.0}, "ts": self.now}
        sel = self.qm.select_candidates("system_1_5", "openai", LEAD, now_utc=self.now, pin_requested=True)
        self.assertEqual(sel.model_key, LEAD)

    def test_provider_says_exhausted_is_only_displayed_by_default(self) -> None:
        self.qm._remote_usage["opencode_go_basic"] = {"percent": {"5h": 19.95}, "ts": self.now}
        sel = self.qm.select_candidates("system_1_5", "openai", LEAD, now_utc=self.now, pin_requested=True)
        self.assertEqual(sel.model_key, LEAD)  # informational by default
        self.qm.pools["opencode_go_basic"]["remote_exhaustion_mode"] = "hard"
        hard = self.qm.select_candidates("system_1_5", "openai", LEAD, now_utc=self.now, pin_requested=True)
        self.assertNotEqual(hard.model_key, LEAD)
        self.assertIn("5h_exhausted(remote ", hard.skipped_reasons[LEAD])

    def test_stale_reading_is_marked_and_the_pool_fails_open(self) -> None:
        self.qm.record_usage(LEAD, units_override=20.0, now_utc=self.now)  # local estimate looks exhausted
        stale = self.now - timedelta(seconds=REMOTE_USAGE_TTL_SEC + 1)
        self.qm._remote_usage["opencode_go_basic"] = {"percent": {"5h": 99.0}, "ts": stale}
        sel = self.qm.select_candidates("system_1_5", "openai", LEAD, now_utc=self.now, pin_requested=True)
        self.assertEqual(sel.model_key, LEAD)  # percent limits vs estimated credits: no verdict, fail open
        snap = self.qm.status_snapshot(self.now)["pools"]["opencode_go_basic"]["remote_usage"]
        self.assertEqual(snap["percent"], {"5h": 99.0})
        self.assertFalse(snap["authoritative"])

    def test_no_network_unless_started_and_pool_config_declares_the_endpoint(self) -> None:
        self.assertIsNone(self.qm._remote_thread)
        policy = yaml.safe_load((REPO_ROOT / "proxy_gateway" / "quota_policy.yaml").read_text(encoding="utf-8"))
        self.assertEqual(policy["pools"]["opencode_go_basic"]["usage_endpoint"], "https://opencode.ai/inference/go/v1/usage")
        self.assertEqual(policy["pools"]["opencode_go_basic"]["unit"], "percent")


if __name__ == "__main__":
    unittest.main()
