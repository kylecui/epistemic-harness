"""Runner selection: docker is the canonical POSIX sandbox, host is the fallback.

Policy under test:
  * default `gate_runner` stays `host`, so no existing repo silently changes shell;
  * a repo that opts into `docker` gets `RUNNER_UNAVAILABLE` when the CLI or the
    verify image is missing — never a silent downgrade to the host shell;
  * `auto` prefers docker only when it is actually usable;
  * every verdict records which runner produced it (`evidence[].runner`), so a
    green result is attributable after the fact.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

PACK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK_ROOT))

_spec = importlib.util.spec_from_file_location("eg_runner", PACK_ROOT / "orchestrator" / "exit_gate.py")
eg = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
sys.modules["eg_runner"] = eg
_spec.loader.exec_module(eg)

PASS_CMD = "echo ok"


class RunnerSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _engine(self, runner: str) -> "eg.ExitGateEngine":
        return eg.ExitGateEngine(
            repo_dir=self.repo,
            checks=[eg.CheckSpec(name="unit", command=PASS_CMD)],
            gate_runner=runner,
            evidence_policy="enforce",
        )

    def test_default_runner_is_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(eg.ExitGateEngine(repo_dir=Path(tmp)).gate_runner, "host")

    def test_host_runner_records_runner_in_evidence(self):
        decision = self._engine("host").evaluate("done", evidence_policy="enforce")
        self.assertTrue(decision.passed, [(f.name, f.tail) for f in decision.failures])
        self.assertEqual(decision.evidence[0].runner, "host")

    def test_docker_runner_without_cli_reports_unavailable(self):
        with mock.patch.object(eg.shutil, "which", return_value=None):
            decision = self._engine("docker").evaluate("done", evidence_policy="enforce")
        self.assertFalse(decision.passed)
        self.assertEqual(decision.verdict, "red")
        self.assertIn("RUNNER_UNAVAILABLE", decision.failures[0].tail)
        self.assertIn("docker CLI", decision.failures[0].tail)

    def test_docker_runner_without_image_reports_unavailable(self):
        with mock.patch.object(eg.shutil, "which", return_value="/usr/bin/docker"), \
             mock.patch.object(eg.subprocess, "run") as fake_run:
            fake_run.return_value = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="no such image")
            decision = self._engine("docker").evaluate("done", evidence_policy="enforce")
        self.assertFalse(decision.passed)
        self.assertIn("not built", decision.failures[0].tail)

    def test_auto_falls_back_to_host_when_docker_missing(self):
        with mock.patch.object(eg.shutil, "which", return_value=None):
            decision = self._engine("auto").evaluate("done", evidence_policy="enforce")
        self.assertTrue(decision.passed, [(f.name, f.tail) for f in decision.failures])
        self.assertEqual(decision.evidence[0].runner, "host")

    def test_per_check_runner_override_wins(self):
        engine = eg.ExitGateEngine(
            repo_dir=self.repo,
            checks=[eg.CheckSpec(name="unit", command=PASS_CMD, runner="host")],
            gate_runner="docker",
            evidence_policy="enforce",
        )
        with mock.patch.object(eg.shutil, "which", return_value=None):
            decision = engine.evaluate("done", evidence_policy="enforce")
        self.assertTrue(decision.passed, [(f.name, f.tail) for f in decision.failures])
        self.assertEqual(decision.evidence[0].runner, "host")

    def test_config_file_carries_runner_settings(self):
        cfg = self.repo / ".pi"
        cfg.mkdir()
        (cfg / "exit_gate.json").write_text(json.dumps({
            "gate_runner": "docker",
            "verify_image": "custom-verify:1",
            "checks": [{"name": "unit", "command": PASS_CMD}],
        }), encoding="utf-8")
        engine = eg.ExitGateEngine.from_repo_config(self.repo)
        self.assertEqual(engine.gate_runner, "docker")
        self.assertEqual(engine.verify_image, "custom-verify:1")

    def test_ledger_records_runner(self):
        self._engine("host").evaluate("done", evidence_policy="enforce")
        ledger = self.repo / ".pi" / "loop_ledger.jsonl"
        records = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
        self.assertIn("evidence", records[0])
        self.assertEqual(records[0]["evidence"], ["unit"])


if __name__ == "__main__":
    unittest.main()
