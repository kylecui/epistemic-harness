"""Incremental test selector: safety properties (over-select, never under-select)."""

from __future__ import annotations

import importlib.util
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


if __name__ == "__main__":
    unittest.main()
