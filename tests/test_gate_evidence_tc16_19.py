"""TC-16..TC-19 — issue #2: quantified/completeness claims must bind to executed evidence.

Covers the two failure layers of issue #2:
  * zero-check green: a repo with no `.pi/exit_gate.json` (or empty `checks`)
    previously returned `passed=True` for any completion claim;
  * assertion-evidence binding: a "100% / 全部 / 无遗漏" claim must name a check
    the gate actually executed in the same turn, or be explicitly qualified.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PACK_ROOT = Path(__file__).resolve().parent.parent
EXIT_GATE_PATH = PACK_ROOT / "orchestrator" / "exit_gate.py"
sys.path.insert(0, str(PACK_ROOT))


def _load_exit_gate():
    spec = importlib.util.spec_from_file_location("exit_gate_evidence", EXIT_GATE_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["exit_gate_evidence"] = mod
    spec.loader.exec_module(mod)
    return mod


eg = _load_exit_gate()

CLAIM_TEXT = "扫描完成：22 个页面全部完成，无遗漏。"

# Portable check commands: no interpreter launch, no `printf` — the shell's own
# `echo` / `exit` work in both cmd.exe and sh, so these fixtures cannot flake on
# a transient process-launch failure.
PASS_CMD = "echo ok"
FAIL_CMD = "exit 1"



class GateEvidenceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=self.repo, check=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @staticmethod
    def _why(decision) -> str:
        """Failure diagnostic: keeps a flake self-explaining instead of silent."""
        return (
            f"verdict={decision.verdict} passed={decision.passed} "
            f"failures={[(f.name, f.exit_code, f.tail[-120:]) for f in decision.failures]} "
            f"evidence={[(e.name, e.exit_code, e.tail[-120:]) for e in decision.evidence]} "
            f"residue={decision.residue_files} errors={decision.claim_errors}"
        )

    def _engine(self, checks=None, policy="enforce"):
        return eg.ExitGateEngine(repo_dir=self.repo, checks=checks or [], evidence_policy=policy)


class ZeroCheckTests(GateEvidenceTestCase):
    """TC-16: green must never come from "nothing was checked"."""

    def test_tc16_no_config_no_claims_blocks_under_enforce(self):
        engine = eg.ExitGateEngine.from_repo_config(self.repo)  # no .pi/exit_gate.json
        self.assertEqual(engine.checks, [])
        decision = engine.evaluate(CLAIM_TEXT, evidence_policy="enforce")
        self.assertFalse(decision.passed)
        self.assertEqual(decision.verdict, "no_evidence")
        self.assertIn("NO_EVIDENCE", decision.bounce_prompt)

    def test_tc16_warn_policy_flags_but_passes_legacy_repos(self):
        engine = self._engine(policy="warn")
        decision = engine.evaluate("改好了。", evidence_policy="warn")
        self.assertTrue(decision.passed)
        self.assertEqual(decision.verdict, "no_evidence")
        self.assertTrue(any("未执行任何校验" in w for w in decision.warnings))


class ClaimBindingTests(GateEvidenceTestCase):
    """TC-17/18/19: claims bind to executed checks, counts, or explicit qualifiers."""

    def _passing_engine(self):
        checks = [eg.CheckSpec(name="page_scan", command=PASS_CMD)]
        return self._engine(checks=checks)

    def test_tc17_bound_claim_with_green_check_passes(self):
        engine = self._passing_engine()
        decision = engine.evaluate(
            CLAIM_TEXT,
            claims=[{"text": "全部完成，无遗漏", "check": "page_scan", "expected_count": 1}],
            evidence_policy="enforce",
        )
        self.assertTrue(decision.passed, self._why(decision))
        self.assertEqual(decision.verdict, "green")
        self.assertEqual([e.name for e in decision.evidence], ["page_scan"])
        self.assertEqual(decision.evidence[0].counted, 1)

    def test_tc17b_caller_supplied_verification_command_counts_as_evidence(self):
        engine = self._engine()
        decision = engine.evaluate(
            CLAIM_TEXT,
            claims=[{"text": "全部完成", "check": "verify-1"}],
            verification_commands=[PASS_CMD],
            evidence_policy="enforce",
        )
        self.assertTrue(decision.passed, self._why(decision))
        self.assertEqual(decision.evidence[0].source, "caller")
        self.assertEqual(decision.verdict, "green")

    def test_tc18_red_check_still_blocks_bound_claim(self):
        checks = [eg.CheckSpec(name="page_scan", command=FAIL_CMD)]
        engine = self._engine(checks=checks)
        decision = engine.evaluate(
            CLAIM_TEXT, claims=[{"text": "全部完成", "check": "page_scan"}], evidence_policy="enforce"
        )
        self.assertFalse(decision.passed)
        self.assertEqual(decision.verdict, "red")
        self.assertEqual([f.name for f in decision.failures], ["page_scan"])

    def test_tc19_qualified_claim_is_not_reported_as_unbound(self):
        engine = self._passing_engine()
        decision = engine.evaluate("抽样 5/22 页，其余未验证。", evidence_policy="enforce")
        self.assertTrue(decision.passed, self._why(decision))
        self.assertEqual(decision.unbound_claims, [])

    def test_tc19b_unbound_claim_blocks_under_enforce(self):
        engine = self._passing_engine()
        decision = engine.evaluate(CLAIM_TEXT, evidence_policy="enforce")
        self.assertFalse(decision.passed)
        self.assertEqual(decision.verdict, "unbound_claim")
        self.assertTrue(decision.unbound_claims)
        self.assertIn("Unbound quantified claim", decision.bounce_prompt)

    def test_claim_naming_unexecuted_check_is_an_error(self):
        engine = self._passing_engine()
        decision = engine.evaluate(
            "100% 覆盖", claims=[{"text": "100% 覆盖", "check": "i18n_keys"}], evidence_policy="enforce"
        )
        self.assertFalse(decision.passed)
        self.assertTrue(any("i18n_keys" in e for e in decision.claim_errors))

    def test_expected_count_mismatch_is_red(self):
        checks = [eg.CheckSpec(name="page_scan", command=PASS_CMD)]
        engine = self._engine(checks=checks)
        decision = engine.evaluate(
            CLAIM_TEXT,
            claims=[{"text": "22 个页面全部完成", "check": "page_scan", "expected_count": 22}],
            evidence_policy="enforce",
        )
        self.assertFalse(decision.passed)
        self.assertEqual(decision.verdict, "red")
        self.assertTrue(any("claim-count" in f.name for f in decision.failures))

    def test_code_fence_claims_are_exempt(self):
        self.assertEqual(
            eg.extract_unbound_claims("说明如下：\n```\n全部 100% 覆盖\n```\n已完成。"), []
        )


class LoopLedgerTests(GateEvidenceTestCase):
    """Cross-turn loop memory: the same fingerprint must escalate instead of repeating."""

    def _failing_engine(self):
        checks = [eg.CheckSpec(name="unit", command=FAIL_CMD)]
        return self._engine(checks=checks)

    def test_ledger_records_and_counts_repeats(self):
        for _ in range(3):
            engine = self._failing_engine()  # fresh instance == fresh turn
            engine.evaluate("修了一下", evidence_policy="enforce")
        ledger = self.repo / ".pi" / "loop_ledger.jsonl"
        self.assertTrue(ledger.exists())
        records = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(records), 3)
        self.assertTrue(all(r["verdict"] == "red" for r in records))

    def test_third_repeat_escalates_to_root_cause(self):
        decisions = []
        for _ in range(3):
            engine = self._failing_engine()
            decisions.append(engine.evaluate("修了一下", evidence_policy="enforce"))
        self.assertFalse(decisions[0].escalate_root_cause)
        self.assertTrue(decisions[2].escalate_root_cause)
        self.assertIn("LOOP_LEDGER", decisions[2].bounce_prompt)
        self.assertEqual(decisions[2].action, "escalate_and_bounce")


if __name__ == "__main__":
    unittest.main()
