"""G6/G7/G8 + observability tooling — memory reuse stats, capability matrix, dispatch parsing."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PACK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK_ROOT))

from mcp_server import memory_stats as ms  # noqa: E402


def _load_script(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, PACK_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


cap_matrix = _load_script("cap_matrix_t", "scripts/capability_matrix.py")
analyze = _load_script("analyze_t", "scripts/analyze_dispatches.py")


class MemoryStatsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / ".pi").mkdir()
        (self.root / "knowledge" / "l5_store").mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _claim(self, cid: str, created: str) -> None:
        path = self.root / "knowledge" / "l5_store" / f"{created[:7]}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"claim_id": cid, "claim": f"c-{cid}",
                                 "created_at": f"{created}T00:00:00+00:00"}) + "\n")

    def _ledger(self, lines: list[dict]) -> None:
        text = "".join(json.dumps({**{"kind": "gate", "ts": "2026-11-21T00:00:00+00:00"}, **l},
                                  ensure_ascii=False) + "\n" for l in lines)
        (self.root / ".pi" / "loop_ledger.jsonl").write_text(text, encoding="utf-8")

    def test_hit_ratio_computed_from_memory_refs(self):
        self._ledger([
            {"verdict": "green", "ts": "2026-11-21T00:00:00+00:00", "memory_refs": ["L5-001"]},
            {"verdict": "green", "ts": "2026-11-21T00:01:00+00:00", "memory_refs": []},
            {"verdict": "green", "ts": "2026-11-21T00:02:00+00:00", "memory_refs": ["L5-001", "L1-CAP-001"]},
        ])
        report = ms.stats(self.root)
        self.assertEqual(report["gate_runs"], 3)
        self.assertEqual(report["runs_citing_memory"], 2)
        self.assertAlmostEqual(report["hit_ratio"], 2 / 3, places=3)
        self.assertEqual(report["distinct_cited"], ["L1-CAP-001", "L5-001"])

    def test_old_never_cited_claim_is_archive_candidate(self):
        self._claim("L5-OLD", "2025-01-01")
        self._claim("L5-NEW", "2026-11-20")
        report = ms.stats(self.root, retention_days=90)
        self.assertEqual([c["id"] for c in report["archive_candidates"]], ["L5-OLD"])

    def test_cited_claim_is_not_archived(self):
        self._claim("L5-OLD", "2025-01-01")
        self._ledger([{"verdict": "green", "memory_refs": ["L5-OLD"]}])
        report = ms.stats(self.root, retention_days=90)
        self.assertEqual(report["archive_candidates"], [])

    def test_archive_moves_rows_and_keeps_them(self):
        self._claim("L5-OLD", "2025-01-01")
        result = ms.archive(self.root, retention_days=90)
        self.assertEqual(result["moved"], 1)
        archived = self.root / "knowledge" / "l5_store" / "archive" / "2025-01.jsonl"
        self.assertTrue(archived.exists())
        self.assertIn("L5-OLD", archived.read_text(encoding="utf-8"))
        active = self.root / "knowledge" / "l5_store" / "2025-01.jsonl"
        self.assertNotIn("L5-OLD", active.read_text(encoding="utf-8"))


class CapabilityMatrixTests(unittest.TestCase):
    def _policy(self, extra: str = "") -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "quota_policy.yaml"
        path.write_text(
            "pools:\n  p1: {last_option: false}\nmodels:\n"
            "  m-full:\n    pool: p1\n    protocol: openai\n    api_key_env: KEY_A\n"
            "    upstream_model: m1\n"
            "  m-clamped:\n    pool: p1\n    protocol: openai\n    api_key_env: KEY_B\n"
            "    upstream_model: m2\n    max_effort: low\n"
            "  m-copilot:\n    pool: p1\n    protocol: openai\n    auth: copilot\n"
            "    upstream_model: m3\n" + extra,
            encoding="utf-8")
        return path

    def test_free_combination_matrix(self):
        matrix = cap_matrix.build_matrix(self._policy(), env={"KEY_A": "x", "KEY_B": "y"})
        rows = {r["model"]: r for r in matrix["models"]}
        self.assertEqual(rows["m-full"]["efforts_allowed"], ["minimal", "low", "medium", "high"])
        self.assertEqual(rows["m-full"]["efforts_clamped"], [])
        self.assertEqual(rows["m-clamped"]["efforts_allowed"], ["minimal", "low"])
        self.assertEqual(rows["m-clamped"]["efforts_clamped"], ["medium", "high"])
        self.assertTrue(rows["m-copilot"]["credentials_present"], "auth-backed model needs no api key")

    def test_missing_credentials_are_flagged_not_hidden(self):
        matrix = cap_matrix.build_matrix(self._policy(), env={})
        rows = {r["model"]: r for r in matrix["models"]}
        self.assertFalse(rows["m-full"]["credentials_present"])
        self.assertTrue(rows["m-copilot"]["credentials_present"])


class AnalyzeDispatchesTests(unittest.TestCase):
    def test_parse_dispatches_and_guard_log(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "traces").mkdir()
        (root / "traces" / "dispatches.jsonl").write_text(
            json.dumps({"ts": "2026-11-21T00:00:00", "profile": "coder", "routed_tier": "system_1_5",
                        "selected_model": "m1", "effort": "low", "attempts": 1}) + "\n" +
            json.dumps({"ts": "2026-11-21T00:01:00", "profile": "deep", "routed_tier": "system_2",
                        "selected_model": "m2", "effort": "high", "attempts": 2, "critic_model": "m3"}) + "\n",
            encoding="utf-8")
        guard = root / "guard.log"
        guard.write_text(
            "2026-11-21T00:00:00Z [sub-agent] start mcp__epistemic_orchestrator__dispatch_subagent id=t1 profile=coder\n"
            "2026-11-21T00:00:05Z [sub-agent] done mcp__epistemic_orchestrator__dispatch_subagent model=m1 tier=system_1_5 effort=low\n"
            "2026-11-21T00:02:00Z [sub-agent] done codemode (no model metadata in result)\n",
            encoding="utf-8")
        dispatches = analyze.read_dispatches(root / "traces" / "dispatches.jsonl")
        events = analyze.read_guard_events(guard)
        summary = analyze.summarize(dispatches, events)
        self.assertEqual(summary["dispatches_recorded"], 2)
        self.assertEqual(summary["by_profile"], {"coder": 1, "deep": 1})
        self.assertEqual(summary["with_critic_pass"], 1)
        self.assertEqual(summary["guard_log"], {"starts": 1, "dones_with_metadata": 1, "dones_without_metadata": 1})

    def test_real_repo_matrix_loads(self):
        matrix = cap_matrix.build_matrix()
        self.assertGreaterEqual(len(matrix["models"]), 5)
        self.assertTrue(all("efforts_allowed" in r for r in matrix["models"]))


if __name__ == "__main__":
    unittest.main()
