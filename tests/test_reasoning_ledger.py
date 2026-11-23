"""ReasoningRecord ledger: schema validation, append-only, information-flow closure."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import orchestrator.reasoning_ledger as rl  # noqa: E402


def _record(rid: str, ts, refs=None, source_ids=None) -> dict:
    return {
        "schema": "reasoning-record/v1",
        "record_id": rid,
        "tier": "Tier 1.5",
        "mode": "converge",
        "claims": [{
            "text": "claim text",
            "layer": "L2",
            "confidence_cap": "L2",
            "source_ids": source_ids or [],
        }],
        "evidence_refs": refs or [],
        "open_gaps": [],
        "ts": ts,
    }


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_path, self._orig_state = rl.LEDGER_PATH, rl._state
        self._orig_records, self._orig_loaded = rl._records, rl._loaded
        rl.LEDGER_PATH = Path(self._tmp.name) / "ledger.jsonl"
        rl._state, rl._records, rl._loaded = {}, [], False

    def tearDown(self):
        rl.LEDGER_PATH = self._orig_path
        rl._state, rl._records, rl._loaded = self._orig_state, self._orig_records, self._orig_loaded
        self._tmp.cleanup()

    def test_happy_path_append(self):
        reg = rl.register_evidence("ev-1", 1000.0)
        self.assertTrue(reg["ok"])
        res = rl.submit_record(_record("r-1", 1001.0, refs=["ev-1"], source_ids=["ev-1"]))
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["ledger_size"], 1)

    def test_forward_reference_rejected(self):
        rl.register_evidence("ev-1", 2000.0)
        res = rl.submit_record(_record("r-1", 1001.0, refs=["ev-1"]))
        self.assertFalse(res["ok"])
        self.assertTrue(any("information-flow" in v for v in res["violations"]))

    def test_unknown_reference_rejected(self):
        res = rl.submit_record(_record("r-1", 1001.0, refs=["never-registered"]))
        self.assertFalse(res["ok"])
        self.assertTrue(any("not registered" in v for v in res["violations"]))

    def test_append_only_duplicate_rejected(self):
        rl.register_evidence("ev-1", 1000.0)
        self.assertTrue(rl.submit_record(_record("r-1", 1001.0, refs=["ev-1"]))["ok"])
        res = rl.submit_record(_record("r-1", 1002.0))
        self.assertFalse(res["ok"])
        self.assertTrue(any("append-only" in v for v in res["violations"]))

    def test_schema_violation_rejected_no_write(self):
        bad = _record("r-1", 1001.0)
        del bad["claims"]
        res = rl.submit_record(bad)
        self.assertFalse(res["ok"])
        self.assertEqual(rl.ledger_status()["records"], 0)

    def test_persistence_reload(self):
        rl.register_evidence("ev-1", 1000.0)
        rl.submit_record(_record("r-1", 1001.0, refs=["ev-1"]))
        rl._state, rl._records, rl._loaded = {}, [], False  # simulate restart
        self.assertEqual(rl.ledger_status()["records"], 1)
        res = rl.submit_record(_record("r-2", 1002.0, refs=["ev-1", "r-1"]))
        self.assertTrue(res["ok"], res)  # prior record id usable as evidence


if __name__ == "__main__":
    unittest.main()
