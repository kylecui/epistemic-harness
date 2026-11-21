"""G1/G2/G4/G5 — task contract, failure ownership, verifier tamper signal, batch docker.

These four close the loop-side gaps that made the gate necessary but not
sufficient: a goal anchor (contract), an owner for every failure, a signal when
the verifier itself changed, and one container for many checks.
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
sys.path.insert(0, str(PACK_ROOT))

_spec = importlib.util.spec_from_file_location("eg_loop", PACK_ROOT / "orchestrator" / "exit_gate.py")
eg = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
sys.modules["eg_loop"] = eg
_spec.loader.exec_module(eg)

from orchestrator import task_contract as tc  # noqa: E402

PASS_CMD = "echo ok"
FAIL_CMD = "exit 1"


class LoopTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=self.repo, check=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _engine(self, checks, policy="enforce", runner="host"):
        return eg.ExitGateEngine(repo_dir=self.repo, checks=checks, evidence_policy=policy,
                                 gate_runner=runner)


class TaskContractTests(LoopTestCase):
    def _contract(self, predicates, task_id="t-1"):
        contract = tc.TaskContract(task_id=task_id, goal="close the thing",
                                   predicates=[tc.Predicate(**p) for p in predicates])
        tc.save(self.repo, contract)
        return contract

    def test_contract_roundtrip(self):
        contract = self._contract([{"id": "P1", "statement": "tests pass", "check": "unit"}])
        loaded = tc.load(self.repo)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.task_id, contract.task_id)
        self.assertEqual(loaded.predicates[0].check, "unit")

    def test_all_predicates_closed_means_green(self):
        self._contract([{"id": "P1", "statement": "tests pass", "check": "unit"}])
        decision = self._engine([eg.CheckSpec(name="unit", command=PASS_CMD)]).evaluate("done")
        self.assertTrue(decision.passed, decision.unclosed_predicates)
        self.assertEqual(decision.verdict, "green")
        self.assertEqual(decision.unclosed_predicates, [])

    def test_predicate_naming_unexecuted_check_blocks(self):
        self._contract([{"id": "P1", "statement": "i18n scan", "check": "i18n_scan"}])
        decision = self._engine([eg.CheckSpec(name="unit", command=PASS_CMD)]).evaluate("done")
        self.assertFalse(decision.passed)
        self.assertEqual(decision.verdict, "unclosed_predicate")
        self.assertEqual(decision.unclosed_predicates[0]["status"], "check_not_executed")
        self.assertIn("Unclosed predicate P1", decision.bounce_prompt)

    def test_failed_predicate_check_reports_check_failed(self):
        self._contract([{"id": "P1", "statement": "tests pass", "check": "unit"}])
        decision = self._engine([eg.CheckSpec(name="unit", command=FAIL_CMD)]).evaluate("done")
        self.assertFalse(decision.passed)
        self.assertEqual(decision.unclosed_predicates[0]["status"], "check_failed")

    def test_optional_predicate_is_not_enforced(self):
        self._contract([{"id": "P1", "statement": "nice to have", "check": "nope", "required": False}])
        decision = self._engine([eg.CheckSpec(name="unit", command=PASS_CMD)]).evaluate("done")
        self.assertTrue(decision.passed, decision.unclosed_predicates)


class FailureClassTests(LoopTestCase):
    def test_code_defect_is_classified(self):
        decision = self._engine([eg.CheckSpec(name="unit", command=FAIL_CMD)]).evaluate("done")
        classes = {c["class"] for c in decision.failure_classes}
        self.assertIn("code_defect", classes)
        self.assertIn("Failure class [code_defect]", decision.bounce_prompt)

    def test_missing_runner_is_env_missing(self):
        from unittest import mock
        with mock.patch.object(eg.shutil, "which", return_value=None):
            decision = self._engine([eg.CheckSpec(name="unit", command=PASS_CMD)], runner="docker").evaluate("done")
        self.assertEqual(decision.failure_classes[0]["class"], "env_missing")
        self.assertIn("image", decision.failure_classes[0]["action"] + decision.failures[0].tail)

    def test_claim_binding_error_is_underdetermined(self):
        decision = self._engine([eg.CheckSpec(name="unit", command=PASS_CMD)]).evaluate(
            "100% 覆盖", claims=[{"text": "100% 覆盖", "check": "never_ran"}])
        self.assertIn("underdetermined", {c["class"] for c in decision.failure_classes})

    def test_unexecuted_evidence_classified_as_underdetermined(self):
        decision = self._engine([]).evaluate("done")
        self.assertEqual(decision.verdict, "no_evidence")
        self.assertIn("underdetermined", {c["class"] for c in decision.failure_classes})


class VerifierTamperTests(LoopTestCase):
    def test_ledger_records_verifier_hash(self):
        self._engine([eg.CheckSpec(name="unit", command=PASS_CMD)]).evaluate("done")
        rec = json.loads((self.repo / ".pi" / "loop_ledger.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertTrue(rec["verifier"])

    def test_verifier_change_after_red_run_is_surfaced(self):
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
        self._engine([eg.CheckSpec(name="unit", command=FAIL_CMD)]).evaluate("done")
        (self.repo / "tests" / "test_x.py").write_text("def test_x():\n    assert 1\n", encoding="utf-8")
        decision = self._engine([eg.CheckSpec(name="unit", command=PASS_CMD)]).evaluate("done")
        self.assertTrue(decision.passed)
        self.assertTrue(decision.verifier_changed, "a verifier edit after a red run must be reported")
        self.assertIn("verifier_changed", decision.warnings[0])

    def test_no_warning_when_verifier_untouched(self):
        self._engine([eg.CheckSpec(name="unit", command=FAIL_CMD)]).evaluate("done")
        decision = self._engine([eg.CheckSpec(name="unit", command=PASS_CMD)]).evaluate("done")
        self.assertEqual(decision.verifier_changed, [])


class BatchDockerTests(LoopTestCase):
    def test_batch_used_only_when_every_check_is_docker(self):
        engine = self._engine([eg.CheckSpec(name="a", command=PASS_CMD), eg.CheckSpec(name="b", command=PASS_CMD)],
                              runner="host")
        calls: list = []
        real_run = subprocess.run

        def fake_run(cmd, **kw):
            if "status" not in (cmd if isinstance(cmd, str) else " ".join(cmd)):
                calls.append(cmd)
            return real_run(cmd, **kw)

        from unittest import mock
        with mock.patch.object(eg.subprocess, "run", side_effect=fake_run):
            engine.evaluate("done")
        self.assertEqual(len(calls), 2, f"host runner must run each check separately, got {calls}")

    def test_batch_script_contains_sentinels_for_each_check(self):
        engine = self._engine([eg.CheckSpec(name="a", command="echo A"), eg.CheckSpec(name="b", command="echo B")],
                              runner="docker")
        captured: dict[str, list[str]] = {}

        def fake_run(cmd, **kw):
            if isinstance(cmd, list) and cmd and cmd[0] == "docker":
                captured["cmd"] = cmd
                out = "__HARNESS_SEG_0\nA\n__HARNESS_RC_0=0\n__HARNESS_SEG_1\nB\n__HARNESS_RC_1=1\n"
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=out, stderr="")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        from unittest import mock
        with mock.patch.object(engine, "_runner_ready", return_value=(True, "ok")), \
             mock.patch.object(eg.subprocess, "run", side_effect=fake_run):
            decision = engine.evaluate("done")

        script = captured["cmd"][-1]
        self.assertIn("__HARNESS_SEG_0", script)
        self.assertIn("__HARNESS_RC_1", script)
        self.assertEqual([e.exit_code for e in decision.evidence], [0, 1])
        self.assertTrue(all(e.runner == "docker" for e in decision.evidence))
        self.assertEqual([f.name for f in decision.failures], ["b"])


if __name__ == "__main__":
    unittest.main()
