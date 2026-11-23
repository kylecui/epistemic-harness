"""Unit tests for scripts/harness_version.py (version triangulation)."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.harness_version as hv  # noqa: E402


class VersionTriangulationTests(unittest.TestCase):
    def _fake_repo(self, root: Path, *, spec: str, loaded: str, stamp: str | None) -> Path:
        (root / "harness.yaml").write_text(f"version: {spec}\nname: x\n", encoding="utf-8")
        (root / "AGENTS.md").write_text(
            f"# epistemic-dual-process-harness (v{loaded}) — Agent Runtime Contract\n", encoding="utf-8")
        (root / ".pi").mkdir(exist_ok=True)
        if stamp is not None:
            (root / ".pi" / "installed_version").write_text(stamp + "\n", encoding="utf-8")
        return root

    def _swap_root(self, repo: Path):
        class Guard:
            def __enter__(self):
                self.orig = hv.REPO_ROOT
                hv.REPO_ROOT = repo
            def __exit__(self, *a):
                hv.REPO_ROOT = self.orig
        return Guard()

    def test_aligned_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._fake_repo(Path(tmp), spec="0.5.1", loaded="0.5.1", stamp="v0.5.1")
            with self._swap_root(repo):
                info = hv.collect()
            self.assertEqual(info["drift"], [])

    def test_spec_loaded_drift_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._fake_repo(Path(tmp), spec="0.5.2", loaded="0.5.1", stamp="v0.5.1")
            with self._swap_root(repo):
                info = hv.collect()
            self.assertTrue(any("compile_clients" in d for d in info["drift"]))

    def test_installed_drift_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._fake_repo(Path(tmp), spec="0.5.1", loaded="0.5.1", stamp="v0.5.0")
            with self._swap_root(repo):
                info = hv.collect()
            self.assertTrue(any("upgrade.py" in d for d in info["drift"]))

    def test_json_output_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._fake_repo(Path(tmp), spec="0.5.1", loaded="0.5.1", stamp="v0.5.1")
            with self._swap_root(repo):
                info = hv.collect()
            parsed = json.loads(json.dumps(info))
            for key in ("spec_version", "loaded_contract_version", "installed_version", "drift"):
                self.assertIn(key, parsed)


if __name__ == "__main__":
    unittest.main()
