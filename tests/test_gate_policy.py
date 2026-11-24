"""The five former host gate entries now live in gate_policy.py, executed in the verify container.

Correspondence is pinned both ways so a check cannot be added on one side only, and the aggregated
script must actually pass on the current repo (it becomes part of every turn's exit gate).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _load():
    spec = importlib.util.spec_from_file_location("gate_policy_under_test", REPO_ROOT / "scripts" / "gate_policy.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate_policy = _load()
FORMER_HOST_CHECKS = {
    "public_language", "experiment_runner_declared", "eol_policy", "routing_validate", "docs_fresh",
}


class GatePolicyTests(unittest.TestCase):
    def test_gate_keeps_exactly_one_entry_and_it_is_the_containerized_one(self) -> None:
        gate = json.loads((REPO_ROOT / ".pi" / "exit_gate.json").read_text(encoding="utf-8"))
        names = [c["name"] for c in gate["checks"]]
        self.assertEqual(names, ["unit_tests"])
        self.assertIn("--policy", gate["checks"][0]["command"])

    def test_policy_check_names_match_the_former_host_entries(self) -> None:
        self.assertEqual({name for name, _s, _a in gate_policy.POLICY_CHECKS}, FORMER_HOST_CHECKS)

    def test_aggregated_check_passes_on_the_current_repo(self) -> None:
        # The real thing: every policy check green right now. A red here blocks the gate,
        # so it must mean a repo problem, never an environment problem.
        self.assertEqual(gate_policy.main(), 0)


if __name__ == "__main__":
    unittest.main()
