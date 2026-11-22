"""Docs freshness gate: version alignment, compiled clients, install doc, orphan docs."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

PACK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK_ROOT))


def _load():
    spec = importlib.util.spec_from_file_location("check_docs_t", PACK_ROOT / "scripts" / "check_docs.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["check_docs_t"] = mod
    spec.loader.exec_module(mod)
    return mod


cd = _load()


def _make_repo(tmp: Path) -> Path:
    """Minimal compliant repo skeleton."""
    (tmp / "scripts").mkdir()
    (tmp / "docs").mkdir()
    (tmp / "harness.yaml").write_text("version: 9.9.9\nname: t\n", encoding="utf-8")
    (tmp / "README.md").write_text("# T v9.9.9\n", encoding="utf-8")
    (tmp / "docs" / "workplan-v0.4.md").write_text("# v9.9.9\n", encoding="utf-8")
    (tmp / "INSTALL.md").write_text("Platform FULL LIMITED matrix\n", encoding="utf-8")
    (tmp / "docs" / "README.md").write_text("index mentions workplan-v0.4.md\n", encoding="utf-8")
    return tmp


class CheckDocsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = _make_repo(Path(self._tmp.name))
        self._orig = cd.REPO_ROOT
        cd.REPO_ROOT = self.repo

    def tearDown(self) -> None:
        cd.REPO_ROOT = self._orig
        self._tmp.cleanup()

    def test_compliant_repo_passes_except_compile(self):
        problems: list[str] = []
        cd.check_version_alignment(problems)
        cd.check_install_doc(problems)
        cd.check_docs_index(problems)
        self.assertEqual(problems, [], problems)

    def test_version_mismatch_flagged(self):
        (self.repo / "README.md").write_text("# T\n", encoding="utf-8")
        problems: list[str] = []
        cd.check_version_alignment(problems)
        self.assertTrue(any("README" in p for p in problems))

    def test_missing_install_flagged(self):
        (self.repo / "INSTALL.md").unlink()
        problems: list[str] = []
        cd.check_install_doc(problems)
        self.assertTrue(any("INSTALL" in p for p in problems))

    def test_missing_matrix_section_flagged(self):
        (self.repo / "INSTALL.md").write_text("no matrix here\n", encoding="utf-8")
        problems: list[str] = []
        cd.check_install_doc(problems)
        self.assertTrue(any("FULL" in p for p in problems))

    def test_orphan_doc_flagged(self):
        (self.repo / "docs" / "orphan.md").write_text("x\n", encoding="utf-8")
        problems: list[str] = []
        cd.check_docs_index(problems)
        self.assertTrue(any("orphan.md" in p for p in problems))

    def test_real_repo_is_fresh(self):
        cd.REPO_ROOT = self._orig
        problems: list[str] = []
        cd.check_version_alignment(problems)
        cd.check_compiled_clients(problems)
        cd.check_install_doc(problems)
        cd.check_docs_index(problems)
        self.assertEqual(problems, [], problems)


class InstallDetectTests(unittest.TestCase):
    def _load_install(self):
        spec = importlib.util.spec_from_file_location("install_t", PACK_ROOT / "scripts" / "install.py")
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules["install_t"] = mod
        spec.loader.exec_module(mod)
        return mod

    def test_detect_runs_and_reports_tier(self):
        inst = self._load_install()
        info = inst.detect()
        for key in ("os", "shell_family", "python", "python_ok", "git", "docker", "support_tier"):
            self.assertIn(key, info)
        self.assertIn(info["support_tier"], ("full", "limited"))

    def test_hvx_wrappers_exist(self):
        self.assertTrue((PACK_ROOT / "scripts" / "hvx").exists())
        self.assertTrue((PACK_ROOT / "scripts" / "hvx.ps1").exists())
        sh = (PACK_ROOT / "scripts" / "hvx").read_text(encoding="utf-8")
        self.assertIn(".venv/Scripts/python.exe", sh)   # venv-first resolution
        self.assertIn("verify.py", sh)

    def test_limited_support_list_present(self):
        inst = self._load_install()
        text = inst.report({"platform": "x", "shell_family": "y", "python": "3.12.0",
                            "python_ok": True, "git": True, "docker": False,
                            "venv_present": False, "os": "Z", "support_tier": "limited"})
        self.assertIn("LIMITED", text)
        self.assertIn("posix sh semantics", text.lower())


if __name__ == "__main__":
    unittest.main()


class ShellIntegrationTests(unittest.TestCase):
    def _load_install(self):
        spec = importlib.util.spec_from_file_location("install_s", PACK_ROOT / "scripts" / "install.py")
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules["install_s"] = mod
        spec.loader.exec_module(mod)
        return mod

    def test_snippet_idempotent(self):
        inst = self._load_install()
        tmp = Path(tempfile.mkdtemp()) / "rc"
        self.assertIn("appended", inst._append_idempotent(tmp, inst._shell_snippet(False)))
        self.assertIn("already present", inst._append_idempotent(tmp, inst._shell_snippet(False)))
        self.assertEqual(tmp.read_text(encoding="utf-8").count(inst.SHELL_MARKER_BEGIN), 1)

    def test_snippet_contents(self):
        inst = self._load_install()
        sh = inst._shell_snippet(False)
        self.assertIn("harness()", sh)
        self.assertIn("alias hvx=", sh)
        ps = inst._shell_snippet(True)
        self.assertIn("function harness", ps)
        self.assertIn("hvx.ps1", ps)


class SkillQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        from orchestrator.skills import SkillRegistry
        self.registry = SkillRegistry(PACK_ROOT / "skills" / "registry.yaml",
                                      PACK_ROOT / "skill_queue" / "pending.yaml")

    def test_harness_skills_registered(self):
        names = {s["name"] for s in self.registry.query("harness", limit=10)}
        self.assertIn("harness-verify", names)
        self.assertIn("harness-status", names)
        self.assertIn("harness-maintain", names)
        self.assertIn("harness-config", names)

    def test_cjk_phrase_query_matches(self):
        # Chinese phrases without spaces must still match (bigram tokenization)
        self.assertEqual(self.registry.query("看看状态", limit=1)[0]["name"], "harness-status")
        self.assertEqual(self.registry.query("编译同步", limit=1)[0]["name"], "harness-maintain")


class KeyPromptTests(unittest.TestCase):
    def _load_install(self, name="install_k"):
        spec = importlib.util.spec_from_file_location(name, PACK_ROOT / "scripts" / "install.py")
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod

    def test_key_vars_derived_from_policy(self):
        inst = self._load_install()
        vars_ = inst.collect_key_vars()
        self.assertIn("ZHIPU_API_KEY", vars_)
        self.assertIn("KIMI_API_KEY", vars_)
        self.assertEqual(vars_, sorted(vars_))

    def test_dotenv_upsert_preserves_comments_and_order(self):
        inst = self._load_install()
        tmp = Path(tempfile.mkdtemp()) / ".env"
        tmp.write_text('A=1\n# comment\nB="2"\n', encoding="utf-8")
        inst._write_dotenv(tmp, {"B": "new", "C": "3"})
        text = tmp.read_text(encoding="utf-8")
        self.assertLess(text.index("A=1"), text.index("# comment"))
        self.assertIn('B="new"', text)
        self.assertIn('C="3"', text)
        self.assertEqual(inst._read_dotenv(tmp)["B"], "new")

    def test_prompt_skipped_when_not_tty(self):
        inst = self._load_install()
        # Force the non-tty path regardless of the invoking shell
        class FakeStdin:
            def isatty(self): return False
        with mock.patch.object(sys, "stdin", FakeStdin()):
            self.assertEqual(inst.prompt_for_keys(), [])


class InstallFailurePathsTests(unittest.TestCase):
    def _load_install(self):
        spec = importlib.util.spec_from_file_location("install_f", PACK_ROOT / "scripts" / "install.py")
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules["install_f"] = mod
        spec.loader.exec_module(mod)
        return mod

    def test_venv_hint_is_actionable(self):
        inst = self._load_install()
        hint = inst.venv_hint()
        self.assertIn("install", hint.lower())
        self.assertIn("re-run", hint)

    def test_limited_warning_posix_shell(self):
        inst = self._load_install()
        text = inst.report({"platform": "Linux", "shell_family": "posix", "python": "3.10.12",
                            "python_ok": True, "git": True, "docker": False,
                            "venv_present": False, "os": "Linux", "support_tier": "limited"})
        low = text.lower()
        self.assertIn("posix sh semantics", low)
        self.assertNotIn("cmd.exe", low)

    def test_shell_targets_skip_powershell_on_posix(self):
        inst = self._load_install()
        names = [n for n, _, _ in inst.shell_targets()]
        if os.name != "nt":
            self.assertNotIn("powershell", names)
        self.assertIn("bashrc", names)


class DispatchDoctorTests(unittest.TestCase):
    def _load_doctor(self):
        spec = importlib.util.spec_from_file_location("doctor_t", PACK_ROOT / "scripts" / "dispatch_doctor.py")
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules["doctor_t"] = mod
        spec.loader.exec_module(mod)
        return mod

    def test_fixture_split_by_timestamp_multiplicity(self):
        doc = self._load_doctor()
        rows = ([{"ts": "2026-11-19T12:00:00+00:00", "agent_id": "coder"}] * 7
                + [{"ts": f"2026-11-21T0{i}:00:00+00:00", "agent_id": "coder"} for i in range(3)])
        real, fixtures = doc.split_fixtures(rows)
        self.assertEqual(len(real), 3)
        self.assertEqual(fixtures, 7)

    def test_consistency_catches_drift(self):
        doc = self._load_doctor()
        ok = [{"ts": "2026-11-21T00:00:00", "agent_id": "explorer", "tier": "system_1", "effort": "low"}]
        bad = [{"ts": "2026-11-21T00:00:01", "agent_id": "explorer", "tier": "system_2", "effort": "high"}]
        self.assertEqual(doc.check_consistency(ok), [])
        self.assertEqual(len(doc.check_consistency(bad)), 2)

    def test_cross_family_detects_same_pool(self):
        doc = self._load_doctor()
        rows = [
            {"ts": "2026-11-21T00:00:00", "agent_id": "coder", "tier": "system_1_5", "effort": "medium",
             "selected_model": "kimi-for-coding", "skipped": {}},
            {"ts": "2026-11-21T00:00:05", "agent_id": "critic", "tier": "system_2_plus", "effort": "high",
             "selected_model": "kimi-k3.1-pro", "skipped": {}},
        ]
        events = doc.check_cross_family(rows)
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["same_pool"], "kimi pool drafting + kimi pool reviewing must be flagged")

    def test_recommendations_fire_on_low_critic_share(self):
        doc = self._load_doctor()
        recs = doc.recommendations([{"agent_id": "coder", "effort": "medium"}] * 12, [], 0.02)
        self.assertTrue(any(r["status"] == "FIRED" and "critic" in r["trigger"] for r in recs))

    def test_skill_registered_and_real_doctor_runs(self):
        from orchestrator.skills import SkillRegistry
        reg = SkillRegistry(PACK_ROOT / "skills" / "registry.yaml", PACK_ROOT / "skill_queue" / "pending.yaml")
        self.assertEqual(reg.query("派发回顾 诊断", limit=1)[0]["name"], "harness-doctor")
        doc = self._load_doctor()
        # Smoke-test the real doctor without making results depend on live traces.
        with mock.patch.object(doc, "load_subagent_rows", return_value=[]):
            result = doc.doctor()
        self.assertIn("recommendations", result)
        self.assertEqual(result["checks"]["C1_mapping_consistency"]["violations"], 0)
