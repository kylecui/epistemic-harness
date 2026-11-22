"""Memory stage 1 — L4/L5 persistence + reuse with inherited confidence cap.

Before this change L5 derivations lived only in process memory: every MCP restart
threw away the most expensive artifact of an analysis. These tests pin the new
behaviour: append-only store, hydration on startup, session-scoped audit by
default, and weakest-link inheritance when a persisted claim is reused.
"""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

import yaml

PACK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK_ROOT))

from mcp_server.dag_engine import EpistemicEngine  # noqa: E402

L1 = {
    "axioms": [{
        "id": "L1-TEST-001",
        "title": "总延迟恒等式",
        "statement": "T_total = T_compute + T_wait",
        "source": "queuing theory",
        "immutable": True,
    }]
}
L2 = {
    "evidence": [{
        "id": "L2-TEST-001",
        "title": "某系统观测",
        "fact": "p99 延迟 400ms",
        "source": "telemetry 2026-11",
        "verified_at": "2026-11-19",
    }]
}
L3 = {
    "heuristics": [{
        "id": "L3-TEST-001",
        "title": "缓存优先",
        "claim": "热数据先走缓存",
        "scope_conditions": ["读多写少"],
        "counter_examples": ["强一致账务写入"],
        "falsifiable": True,
    }]
}


def _seed_repo(root: Path) -> None:
    for rel, payload in (
        ("knowledge/l1_axioms/axioms.yaml", L1),
        ("knowledge/l2_library/evidence.yaml", L2),
        ("knowledge/l3_heuristics/heuristics.yaml", L3),
    ):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")


class MemoryPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        _seed_repo(self.repo)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _engine(self) -> EpistemicEngine:
        # Explicit store_root beats HARNESS_MEMORY_STORE so each test keeps its own store.
        return EpistemicEngine(self.repo, store_root=self.repo)

    def _submit(self, engine: EpistemicEngine, claim_id: str, sources: list[str], tier: str = "L1"):
        # Grounding rule: retrieve every cited store id before citing it.
        for sid in sources:
            if sid.startswith("L1-"):
                engine.query_l1(sid)
            elif sid.startswith("L2-"):
                engine.search_l2(sid)
            elif sid.startswith("L3-"):
                engine.recall_l3(sid)
        return engine.submit_l5_claim({
            "claim_id": claim_id,
            "claim": f"derived conclusion {claim_id}",
            "claimed_tier": tier,
            "source_ids": sources,
        })

    def test_l5_claim_is_appended_to_monthly_store(self):
        engine = self._engine()
        self._submit(engine, "L5-001", ["L1-TEST-001"])
        files = sorted((self.repo / "knowledge" / "l5_store").glob("*.jsonl"))
        self.assertEqual(len(files), 1)
        self.assertRegex(files[0].name, r"^\d{4}-\d{2}\.jsonl$")
        self.assertIn("L5-001", files[0].read_text(encoding="utf-8"))

    def test_restart_hydrates_claims_and_query_finds_them(self):
        self._submit(self._engine(), "L5-001", ["L1-TEST-001"])
        fresh = self._engine()  # simulates an MCP server restart
        recalled = fresh.query_l5("derived")
        self.assertEqual(recalled["total"], 1)
        self.assertEqual(recalled["items"][0]["claim_id"], "L5-001")
        self.assertEqual(recalled["items"][0]["effective_tier"], "L1")

    def test_audit_dag_stays_session_scoped_by_default(self):
        self._submit(self._engine(), "L5-001", ["L1-TEST-001"])
        fresh = self._engine()
        session_view = fresh.audit_dag()
        self.assertEqual(session_view["total_l5_claims"], 0)
        self.assertEqual(session_view["overall_confidence_cap"], "NONE")
        full_view = fresh.audit_dag(include_persisted=True)
        self.assertEqual(full_view["total_l5_claims"], 1)
        self.assertEqual(full_view["overall_confidence_cap"], "L1")

    def test_reused_persisted_claim_inherits_weakest_link_cap(self):
        engine = self._engine()
        self._submit(engine, "L5-001", ["L3-TEST-001"], tier="L3")
        fresh = self._engine()
        record = fresh.submit_l5_claim({
            "claim_id": "L5-002",
            "claim": "reuse the L3-derived prior conclusion",
            "claimed_tier": "L1",
            "source_ids": ["L5-001"],
        })
        self.assertEqual(record["resolved_ancestor_tiers"]["L5-001"], "L5(capped:L3)")
        self.assertEqual(record["effective_tier"], "L3")
        self.assertTrue(record["downgraded"])

    def test_l4_input_survives_restart(self):
        engine = self._engine()
        engine.register_l4_input("L4-TEAM-001", "单人维护, 不引入常驻服务")
        persisted = self.repo / ".pi" / "l4_inputs.jsonl"
        self.assertTrue(persisted.exists())
        fresh = self._engine()
        self.assertIn("L4-TEAM-001", fresh.l4_inputs)
        # A claim grounded only in persisted L4 intent still caps at L3.
        record = fresh.submit_l5_claim({
            "claim_id": "L5-003",
            "claim": "single-maintainer deployment keeps ops cost low",
            "claimed_tier": "L2",
            "source_ids": ["L4-TEAM-001"],
        })
        self.assertEqual(record["effective_tier"], "L3")

    def test_malformed_store_line_is_skipped_not_fatal(self):
        store = self.repo / "knowledge" / "l5_store"
        store.mkdir(parents=True)
        (store / "2026-11.jsonl").write_text(
            "not json\n" + '{"claim_id":"L5-009"}\n', encoding="utf-8"
        )
        engine = self._engine()
        self.assertEqual(engine.query_l5("")["total"], 0)


if __name__ == "__main__":
    unittest.main()
