"""Plane-alignment guards: version detection, settings merge, image tags."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hv = load("harness_version_under_test", "scripts/harness_version.py")
ig = load("install_global_under_test", "scripts/install_global.py")


class TestLoadedDetection(unittest.TestCase):
    def test_detects_header_version(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "AGENTS.md"
            p.write_text("# epistemic-dual-process-harness (v0.3.3) — x\nbody\n", encoding="utf-8")
            self.assertEqual(hv.detect_loaded_version(p), "0.3.3")
            self.assertIsNone(hv.detect_loaded_version(Path(d) / "missing.md"))

    def test_missing_stamp_is_drift_not_silent(self):
        self.assertTrue(any("stamp" in d for d in hv.stamp_drift("0.5.2", None)))
        self.assertEqual(hv.stamp_drift("0.5.2", "v0.5.2"), [])
        self.assertTrue(any("0.5.1" in d for d in hv.stamp_drift("0.5.2", "v0.5.1")))


class TestSettingsMerge(unittest.TestCase):
    def test_merge_is_additive_and_idempotent(self):
        base = {"lastChangelogVersion": "1.6.0"}
        once = ig.merge_pi_settings(base)
        twice = ig.merge_pi_settings(json.loads(json.dumps(once)))
        self.assertEqual(once, twice)
        for token in ("+sh", "+powershell", "+grep", "+find", "+ls"):
            self.assertIn(token, once["defaultTools"])
        self.assertIn("shellPath", once)
        self.assertEqual(once["lastChangelogVersion"], "1.6.0")

    def test_merge_respects_custom_shell_path(self):
        merged = ig.merge_pi_settings({"shellPath": "C:/custom/bash.exe"})
        self.assertEqual(merged["shellPath"], "C:/custom/bash.exe")


class TestImageTags(unittest.TestCase):
    def test_backend_and_sandbox_use_local_tags(self):
        self.assertIn(":local", (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        self.assertIn(":local", (REPO_ROOT / "sandbox" / "compose.yaml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
