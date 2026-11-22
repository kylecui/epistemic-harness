"""Unit tests for orchestrator/hollow_audit.py (P1.6)."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestrator import hollow_audit as ha  # noqa: E402


class HollowAuditTests(unittest.TestCase):
    def test_deterministic_hollow_segments_scored_without_critic(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "audit.jsonl"
            text = "[L3] 方案A。\n适用: 各种情况。\n反例: 因情况而异。\n"
            out = ha.audit_text(text, critic_fn=None, store_path=store)
            scored = [h for h in out["hits"] if h["decided_by"] == "deterministic"]
            self.assertTrue(scored, "filler scope/counter must be scored hollow deterministically")
            self.assertTrue(all(h["substantive"] is False for h in scored))

    def test_critic_verdict_drives_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "audit.jsonl"
            text = "缺陷1: 索引缺失。\n改动点: 加复合索引。\n回退: git revert 迁移提交。\n验收: p99 降至 200ms 以内。\n"
            # critic says the acceptance criterion is hollow -> rate climbs
            out = ha.audit_text(text, critic_fn=lambda p: "NO", store_path=store)
            self.assertEqual(out["hollow_rate"], 1.0)
            self.assertTrue(out["structured_enforcement_recommended"])
            # critic approves the next batches -> rolling rate falls back below trigger
            for _ in range(4):
                out2 = ha.audit_text(text, critic_fn=lambda p: "YES", store_path=store)
            self.assertLessEqual(out2["hollow_rate"], ha.RATE_THRESHOLD)
            self.assertFalse(out2["structured_enforcement_recommended"])

    def test_pending_segments_never_fabricate_verdicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "audit.jsonl"
            text = "验收: p99 降至 200ms 以内。\n"
            out = ha.audit_text(text, critic_fn=None, store_path=store)
            self.assertTrue(all(h["decided_by"] == "pending" for h in out["hits"]))
            self.assertIsNone(out["hollow_rate"])  # nothing scored -> no fabricated rate

    def test_rate_rolls_over_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "audit.jsonl"
            text = "验收: p99 降至 200ms 以内。\n"
            for _ in range(3):
                ha.audit_text(text, critic_fn=lambda p: "NO", store_path=store)
            recs = [json.loads(l) for l in store.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(recs), 3)
            self.assertEqual(recs[-1]["total_scored"], recs[-1]["hollow"])


if __name__ == "__main__":
    unittest.main()
