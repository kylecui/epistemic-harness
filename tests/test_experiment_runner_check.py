"""Gate check: experiment run records must declare their execution runner (issue #13)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECK = REPO_ROOT / "scripts" / "check_experiment_runner_declared.py"


class ExperimentRunnerDeclaredTests(unittest.TestCase):
    def _run(self, runs_dir: Path) -> subprocess.CompletedProcess:
        env = {**os.environ, "EXPERIMENT_RUNS_DIR": str(runs_dir)}
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "check_experiment_runner_declared.py")],
            capture_output=True, text=True, timeout=60, env=env,
        )

    def test_missing_runner_field_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            (runs / "A__t.jsonl").write_text(
                json.dumps({"arm": "A", "runner": "host"}) + "\n" + json.dumps({"arm": "A"}) + "\n",
                encoding="utf-8", newline="\n")
            r = self._run(runs)
            self.assertEqual(r.returncode, 1)
            self.assertIn("missing 'runner'", r.stdout)

    def test_all_declared_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            (runs / "B__t.jsonl").write_text(
                json.dumps({"arm": "B", "runner": "sandbox-container"}) + "\n",
                encoding="utf-8", newline="\n")
            r = self._run(runs)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_unparseable_record_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            (runs / "C__t.jsonl").write_text("{not json}\n", encoding="utf-8", newline="\n")
            r = self._run(runs)
            self.assertEqual(r.returncode, 1)
            self.assertIn("unparseable", r.stdout)


if __name__ == "__main__":
    unittest.main()
