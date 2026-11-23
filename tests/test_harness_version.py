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

class BannerModeTests(unittest.TestCase):
    """--banner: version line always; release notes exactly once per version."""

    def _repo(self, tmp: str, version: str) -> Path:
        repo = Path(tmp)
        (repo / "harness.yaml").write_text(f"version: {version}\nname: x\n", encoding="utf-8")
        (repo / "AGENTS.md").write_text(
            f"# epistemic-dual-process-harness (v{version}) — Agent Runtime Contract\n", encoding="utf-8")
        (repo / ".pi").mkdir(exist_ok=True)
        (repo / ".pi" / "installed_version").write_text(f"v{version}\n", encoding="utf-8")
        (repo / "docs").mkdir(exist_ok=True)
        (repo / "docs" / "RELEASE-NOTES.md").write_text(
            "# Release notes\n\n## v0.5.1\n\n- first note\n- second note\n\n## v0.5.0\n\n- old note\n", encoding="utf-8")
        return repo

    def test_first_banner_shows_notes_and_stamps(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp, "0.5.1")
            lines, stamped = hv.banner_text(repo)
            self.assertTrue(any("contract v0.5.1 loaded" in l for l in lines))
            self.assertTrue(any("first note" in l for l in lines))
            self.assertTrue(stamped)
            self.assertEqual((repo / ".pi" / "last_banner_version").read_text().strip(), "0.5.1")

    def test_second_banner_is_quiet(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp, "0.5.1")
            hv.banner_text(repo)
            lines, stamped = hv.banner_text(repo)
            self.assertFalse(any("first note" in l for l in lines))
            self.assertFalse(stamped)

    def test_new_version_shows_its_own_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp, "0.5.1")
            hv.banner_text(repo)
            (repo / "harness.yaml").write_text("version: 0.5.2\nname: x\n", encoding="utf-8")
            (repo / "AGENTS.md").write_text(
                "# epistemic-dual-process-harness (v0.5.2) — Agent Runtime Contract\n", encoding="utf-8")
            (repo / "docs" / "RELEASE-NOTES.md").write_text(
                "# Release notes\n\n## v0.5.2\n\n- brand new thing\n", encoding="utf-8")
            lines, stamped = hv.banner_text(repo)
            self.assertTrue(any("brand new thing" in l for l in lines))
            self.assertFalse(any("old note" in l for l in lines))
            self.assertTrue(stamped)
