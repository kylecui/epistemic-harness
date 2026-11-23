"""Unit tests for scripts/upgrade.py (backup, idempotency, migration merge)."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.upgrade as up  # noqa: E402


def _fake_repo(root: Path) -> Path:
    (root / ".pi").mkdir(parents=True)
    (root / ".pi" / "exit_gate.json").write_text(
        json.dumps({"checks": [], "residue_globs": ["*.tmp"]}), encoding="utf-8")
    (root / "knowledge").mkdir()
    (root / "knowledge" / "keep.txt").write_text("user data", encoding="utf-8")
    (root / ".env").write_text("KEY=x", encoding="utf-8")
    (root / ".gitignore").write_text(".env\n", encoding="utf-8")
    (root / "harness.yaml").write_text("version: 0.5.0\n", encoding="utf-8")
    return root


class UpgradeTests(unittest.TestCase):
    def test_residue_glob_migration_merges_not_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _fake_repo(Path(tmp))
            note = up.migrate_exit_gate_residue_globs(repo)
            cfg = json.loads((repo / ".pi" / "exit_gate.json").read_text(encoding="utf-8"))
            self.assertIn("*.tmp", cfg["residue_globs"])  # user entry preserved
            self.assertIn(".*tmp*", cfg["residue_globs"])  # new entries merged
            # idempotent
            note2 = up.migrate_exit_gate_residue_globs(repo)
            self.assertIn("already current", note2)

    def test_backup_copies_mutable_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _fake_repo(Path(tmp))
            sink = repo / ".upgrade-backup-test"
            backed = up.backup(repo, sink)
            self.assertIn(".pi", backed)
            self.assertIn("knowledge", backed)
            self.assertEqual((sink / "knowledge" / "keep.txt").read_text(encoding="utf-8"), "user data")
            self.assertTrue((sink / ".env").exists())

    def test_state_makes_migrations_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _fake_repo(Path(tmp))
            state = {"applied": ["v0.5-exit-gate-residue-globs"]}
            pending = [m for m in up.MIGRATIONS if m[0] not in state["applied"]]
            self.assertNotIn("v0.5-exit-gate-residue-globs", [m[0] for m in pending])

    def test_installed_version_defaults_to_0_4_when_stamp_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _fake_repo(Path(tmp))
            orig = up.REPO_ROOT
            up.REPO_ROOT = repo
            try:
                self.assertEqual(up.installed_version(), "0.4.0")
                (repo / ".pi" / "installed_version").write_text("v0.5.0\n", encoding="utf-8")
                self.assertEqual(up.installed_version(), "v0.5.0")
            finally:
                up.REPO_ROOT = orig


if __name__ == "__main__":
    unittest.main()

class EnvSeedingTests(unittest.TestCase):
    """Live WSL incident 2026-11-22: docker compose needs .env (env_file);
    keyless installs should be seeded from .env.example, not fail the upgrade."""

    def test_docker_rebuild_seeds_env_from_example(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _fake_repo(Path(tmp))
            (repo / ".env").unlink()
            (repo / ".env.example").write_text("KEY=\n", encoding="utf-8")
            # stub the subprocess calls so no real docker/health runs
            calls = []
            def fake_run(cmd, **kw):
                calls.append(cmd)
                class R:
                    returncode = 0
                    stderr = ""
                    stdout = '{"status":"ok"}'
                return R()
            orig_run = up.subprocess.run
            up.subprocess.run = fake_run
            orig_root = up.REPO_ROOT
            up.REPO_ROOT = repo
            try:
                note = up.docker_rebuild()
            finally:
                up.subprocess.run = orig_run
                up.REPO_ROOT = orig_root
            self.assertTrue((repo / ".env").exists())
            self.assertIn("seeded", note)
            self.assertEqual(calls[0][:3], ["docker", "compose", "up"])

class UserSkillsSyncTests(unittest.TestCase):
    def test_sync_copies_and_is_idempotent(self):
        import scripts.install_user_skills as ius
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            src = home / "repo" / ".agents" / "skills" / "harness-upgrade"
            src.mkdir(parents=True)
            (src / "SKILL.md").write_text("---\nname: harness-upgrade\n---\n", encoding="utf-8")
            orig_src, orig_home = ius.SOURCE, ius.user_skills_dir
            ius.SOURCE = home / "repo" / ".agents" / "skills"
            ius.user_skills_dir = lambda: home / "user" / ".agents" / "skills"
            try:
                r1 = ius.sync()
                self.assertEqual(r1["copied"], ["harness-upgrade"])
                r2 = ius.sync()
                self.assertEqual(r2["copied"], [])
                r3 = ius.sync(check=True)
                self.assertEqual(r3["missing"], [])
                # drift detection
                (home / "user" / ".agents" / "skills" / "harness-upgrade" / "SKILL.md").write_text(
                    "old", encoding="utf-8")
                r4 = ius.sync(check=True)
                self.assertEqual(r4["missing"], ["harness-upgrade"])
            finally:
                ius.SOURCE, ius.user_skills_dir = orig_src, orig_home

class GlobalInstallTests(unittest.TestCase):
    def test_global_sync_idempotent_and_check(self):
        import scripts.install_global as ig
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            repo = home / "repo"
            (repo / "extensions").mkdir(parents=True)
            (repo / "extensions" / "harness-guard.ts").write_text("// v-test\n", encoding="utf-8")
            (repo / "harness.yaml").write_text("version: 0.5.2\n", encoding="utf-8")
            (repo / "docs").mkdir(exist_ok=True)
            (repo / "docs" / "RELEASE-NOTES.md").write_text("# notes\n", encoding="utf-8")
            (repo / "scripts").mkdir(exist_ok=True)
            (repo / "scripts" / "harness_version.py").write_text("# x\n", encoding="utf-8")
            (repo / "skills" / "pi-native" / "harness-upgrade").mkdir(parents=True)
            (repo / "skills" / "pi-native" / "harness-upgrade" / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
            orig_repo, orig_ext, orig_home = ig.REPO_ROOT, ig.GLOBAL_EXT, ig.HARNESS_HOME
            ig.REPO_ROOT = repo
            ig.GLOBAL_EXT = home / ".pi" / "agent" / "extensions" / "harness-guard.ts"
            ig.HARNESS_HOME = home / ".pi" / "harness"
            try:
                r1 = ig.sync()
                self.assertTrue(any("harness-guard.ts" in c for c in r1["copied"]))
                self.assertTrue((ig.HARNESS_HOME / "scripts" / "harness_version.py").exists())
                self.assertTrue((ig.HARNESS_HOME / "skills" / "harness-upgrade" / "SKILL.md").exists())
                r2 = ig.sync(check=True)
                self.assertEqual(r2["drift"], [])
            finally:
                ig.REPO_ROOT, ig.GLOBAL_EXT, ig.HARNESS_HOME = orig_repo, orig_ext, orig_home

class SkillWrapperTemplateTests(unittest.TestCase):
    def test_wrappers_have_precheck_and_substitution(self):
        import scripts.install_user_skills as ius
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            src = home / "h" / "skills"
            d = src / "harness-version"
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(
                'precheck {{HARNESS_HOME}}/scripts/x\n', encoding="utf-8")
            orig_src, orig_home = ius.SOURCE, ius.user_skills_dir
            ius.SOURCE = src
            ius.user_skills_dir = lambda: home / ".agents" / "skills"
            try:
                r = ius.sync()
                self.assertEqual(r["copied"], ["harness-version"])
                text = (home / ".agents" / "skills" / "harness-version" / "SKILL.md").read_text(encoding="utf-8")
                self.assertIn(str(home / ".pi" / "harness"), text)
                self.assertNotIn("{{HARNESS_HOME}}", text)
            finally:
                ius.SOURCE, ius.user_skills_dir = orig_src, orig_home

    def test_all_wrappers_have_fail_loud_precheck(self):
        base = REPO_ROOT / "skills" / "pi-native"
        for skill_md in sorted(base.glob("*/SKILL.md")):
            text = skill_md.read_text(encoding="utf-8")
            self.assertIn("test -f", text, f"{skill_md}: missing precheck")
            self.assertIn("exit 1", text, f"{skill_md}: precheck must fail loudly")
            self.assertIn("{{HARNESS_HOME}}", text, f"{skill_md}: missing path template")
