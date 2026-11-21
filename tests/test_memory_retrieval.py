"""G3 — hybrid memory retrieval over SQLite FTS5, with explicit tier banks.

Pinned behaviour:
  * Chinese and ASCII both retrieve (ASCII words + CJK bigrams, no external segmenter);
  * banks come back separately per tier — no blended score, ever;
  * L2 older than the TTL is returned as `stale`, not silently dropped or trusted;
  * L5 items persisted by `submit_l5_claim` are searchable;
  * `ensure_db` rebuilds when the item count drifts from the YAML store.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

import yaml

PACK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK_ROOT))

from mcp_server import memory_index as mi  # noqa: E402

L1 = {"axioms": [{"id": "L1-T-001", "title": "串联可靠性", "statement": "R_total = ∏ R_i，串联不自动提升可用性",
                  "source": "reliability", "immutable": True}]}
L2 = {"evidence": [
    {"id": "L2-T-001", "title": "近期观测", "fact": "p99 延迟 400ms", "source": "telemetry",
     "verified_at": "2026-11-19"},
    {"id": "L2-T-002", "title": "过期观测", "fact": "旧的缓存命中率数据", "source": "telemetry 2024",
     "verified_at": "2024-01-01"},
]}
L3 = {"heuristics": [{"id": "L3-T-001", "title": "缓存优先", "claim": "热数据先走缓存",
                      "scope_conditions": ["读多写少"], "counter_examples": ["强一致账务写入"],
                      "falsifiable": True}]}


def _seed(root: Path) -> Path:
    knowledge = root / "knowledge"
    for rel, payload in (
        ("l1_axioms/axioms.yaml", L1),
        ("l2_library/evidence.yaml", L2),
        ("l3_heuristics/heuristics.yaml", L3),
    ):
        path = knowledge / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    return knowledge


class MemoryRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.knowledge = _seed(self.root)
        self.db = self.root / "knowledge" / "memory_index.db"
        self.summary = mi.build(self.db, self.knowledge)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_build_counts_every_tier(self):
        self.assertEqual(self.summary["by_tier"], {"L1": 1, "L2": 2, "L3": 1})

    def test_chinese_query_hits_the_right_tier(self):
        res = mi.recall(self.db, "缓存", tiers=["L3"])
        self.assertEqual([i["id"] for i in res["banks"]["L3"]], ["L3-T-001"])
        self.assertIn("scope", res["banks"]["L3"][0])
        self.assertEqual(res["banks"]["L3"][0]["counter_examples"], "强一致账务写入")

    def test_ascii_query_hits_l1(self):
        res = mi.recall(self.db, "reliability", tiers=["L1"])
        self.assertEqual([i["id"] for i in res["banks"]["L1"]], ["L1-T-001"])

    def test_banks_are_returned_separately(self):
        res = mi.recall(self.db, "延迟")
        self.assertIsInstance(res["banks"], dict)
        self.assertEqual(set(res["banks"]), set(res["route"]["banks"]))
        self.assertIn("never blended", res["route"]["rule"])

    def test_expired_l2_is_stale_not_dropped(self):
        res = mi.recall(self.db, "观测", tiers=["L2"], k=5)
        statuses = {i["id"]: i["status"] for i in res["banks"]["L2"]}
        self.assertEqual(statuses["L2-T-002"], "stale")
        self.assertEqual(statuses["L2-T-001"], "ok")
        self.assertIn("stale", res["policy"])

    def test_l5_store_is_searchable(self):
        store = self.knowledge / "l5_store"
        store.mkdir(parents=True)
        (store / "2026-11.jsonl").write_text(json.dumps({
            "claim_id": "L5-T-001", "claim": "分区期间不可同时强一致与全可用",
            "claimed_tier": "L1", "effective_tier": "L1", "downgraded": False,
            "downgrade_reason": None, "source_ids": ["L1-T-001"],
            "resolved_ancestor_tiers": {"L1-T-001": "L1"}, "assumptions": [],
            "conflicts_with_l1": [], "status": "provisional",
            "created_at": "2026-11-21T00:00:00+00:00",
        }, ensure_ascii=False) + "\n", encoding="utf-8")
        mi.build(self.db, self.knowledge)
        res = mi.recall(self.db, "分区", tiers=["L5"])
        self.assertEqual([i["id"] for i in res["banks"]["L5"]], ["L5-T-001"])

    def test_ensure_db_rebuilds_when_store_grows(self):
        YAML2 = {"evidence": L2["evidence"] + [{"id": "L2-T-003", "title": "新证据",
                                                "fact": "新日志", "source": "telemetry",
                                                "verified_at": "2026-11-20"}]}
        (self.knowledge / "l2_library" / "evidence.yaml").write_text(
            yaml.safe_dump(YAML2, allow_unicode=True), encoding="utf-8")
        state = mi.ensure_db(self.db, self.knowledge)
        self.assertEqual(state["items"], 5)

    def test_route_prefers_l5_for_prior_questions(self):
        self.assertEqual(mi.route("上次那个结论")["banks"][0], "L5")
        self.assertEqual(mi.route("这个定义是什么")["banks"][0], "L1")

    def test_tokenizer_emits_cjk_bigrams(self):
        toks = mi.tokenize("分区可用性").split()
        self.assertIn("分区", toks)
        self.assertIn("可用", toks)


if __name__ == "__main__":
    unittest.main()
