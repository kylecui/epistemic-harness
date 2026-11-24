"""Incremental test selector: safety properties (over-select, never under-select)."""

from __future__ import annotations

import importlib.util
import sys
import json
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("select_tests_under_test", REPO_ROOT / "scripts" / "select_tests.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


st = _load()

MODULES = {
    "test_quota_router": "from proxy_gateway.quota_manager import QuotaManager",
    "test_proxy_gateway": "from proxy_gateway.app import create_app",
    "test_version": "import scripts.harness_version as hv",
}


class SelectionTests(unittest.TestCase):
    def test_source_change_selects_referencing_tests(self):
        sel, _ = st.select(["proxy_gateway/quota_manager.py"], MODULES)
        self.assertEqual(sel, ["test_quota_router"])

    def test_changed_test_file_selects_itself(self):
        sel, _ = st.select(["tests/test_proxy_gateway.py"], MODULES)
        self.assertEqual(sel, ["test_proxy_gateway"])

    def test_nothing_changed_selects_nothing(self):
        sel, _ = st.select([], MODULES)
        self.assertEqual(sel, [])

    def test_docs_and_data_changes_need_no_unit_tests(self):
        sel, _ = st.select(["README.md", "docs/RELEASE-NOTES.md", "experiments/runs/a.jsonl"], MODULES)
        self.assertEqual(sel, [])

    def test_unmapped_python_source_falls_back_to_full(self):
        sel, why = st.select(["scripts/brand_new_unreferenced.py"], MODULES)
        self.assertIsNone(sel)
        self.assertIn("unmapped", why["*"][0])

    def test_global_triggers_force_full_suite(self):
        for path in ("proxy_gateway/quota_policy.yaml", "harness.yaml", "pyproject.toml", "Dockerfile",
                     "docker-compose.yml", "uv.lock", ".pi/exit_gate.json"):
            sel, _ = st.select([path], MODULES)
            self.assertIsNone(sel, f"{path} must force the full suite")

    def test_non_python_unknown_paths_fall_back_to_full(self):
        for path in ("extensions/harness-guard.ts", "scripts/x.ps1", "something.bin"):
            sel, _ = st.select([path], MODULES)
            self.assertIsNone(sel, path)

    def test_too_many_changes_fall_back_to_full(self):
        many = [f"proxy_gateway/f{i}.py" for i in range(st.MAX_CHANGED_FOR_SELECTION + 1)]
        sel, _ = st.select(many, MODULES)
        self.assertIsNone(sel)

    def test_references_requires_real_import_not_substring(self):
        self.assertTrue(st.references("proxy_gateway/quota_manager.py", MODULES["test_quota_router"]))
        self.assertFalse(st.references("proxy_gateway/quota_manager.py", "unrelated text about nothing"))

    def test_every_real_source_file_maps_or_falls_back_never_silently_drops(self):
        # Invariant: for every real .py source file, selection is either a non-empty
        # test list or None (full) -- never an empty selection (= silently untested).
        modules = st.test_modules()
        for path in list(REPO_ROOT.glob("proxy_gateway/*.py")) + list(REPO_ROOT.glob("orchestrator/*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if path.name == "__init__.py":
                continue
            sel, _ = st.select([rel], modules)
            self.assertTrue(sel is None or len(sel) > 0, f"{rel} would be silently untested")

    def test_docker_command_targets_the_verify_container_with_explicit_modules(self) -> None:
        # Policy: tests run in docker; the host only computes which modules to run.
        cmd = st.docker_command(["test_a", "test_b"])
        self.assertEqual(cmd, [sys.executable, "scripts/verify.py", "--runner", "docker", "--policy",
                               "--modules", "tests.test_a", "tests.test_b"])
        self.assertEqual(st.docker_command(None), [sys.executable, "scripts/verify.py", "--runner", "docker", "--policy"])

    def test_exit_gate_config_points_at_the_containerized_command(self) -> None:
        import json
        gate = json.loads((REPO_ROOT / ".pi" / "exit_gate.json").read_text(encoding="utf-8"))
        self.assertEqual([c["name"] for c in gate["checks"]], ["unit_tests"])
        self.assertTrue(gate["checks"][0]["command"].endswith("select_tests.py --docker --policy"))

    def test_cli_accepts_the_exact_arguments_the_gate_passes(self) -> None:
        # The gate config and the CLI are separate files: --policy was passed before it existed
        # and the whole gate died with 'unrecognized arguments' (2026-11-24).
        import json
        import subprocess
        gate = json.loads((REPO_ROOT / ".pi" / "exit_gate.json").read_text(encoding="utf-8"))
        command = next(c["command"] for c in gate["checks"] if c["name"] == "unit_tests")
        flags = [part for part in command.split() if part.startswith("--")]
        help_text = subprocess.run([sys.executable, "scripts/select_tests.py", "--help"],
                                   cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60).stdout
        for flag in flags:
            self.assertIn(flag, help_text, f"gate passes {flag} but the CLI does not accept it")


if __name__ == "__main__":
    unittest.main()
