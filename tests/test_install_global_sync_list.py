"""Every extension in extensions/ must be in install_global's sync list (found 2026-11-24:
model-route-status.ts existed in the repo but a fixed copy list meant it never reached
~/.pi/agent/extensions, so it would have looked like a broken feature)."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import scripts.install_global as installer


# Extensions that belong to this repo only, by design (never installed globally).
PROJECT_LOCAL = {"lab-watcher.ts"}


class SyncListTests(unittest.TestCase):
    def test_every_repo_extension_is_shipped(self) -> None:
        shipped = {src.name for src, _dst in installer._jobs() if src.suffix == ".ts"}
        on_disk = {p.name for p in (REPO_ROOT / "extensions").glob("*.ts")}
        self.assertEqual(on_disk - shipped - PROJECT_LOCAL, set(), "extension not in install_global's sync list")

    def test_project_local_extensions_exist_and_are_not_shipped(self) -> None:
        shipped = {src.name for src, _dst in installer._jobs()}
        for name in PROJECT_LOCAL:
            self.assertTrue((REPO_ROOT / "extensions" / name).exists(), name)
            self.assertNotIn(name, shipped, name)

    def test_sync_list_paths_exist(self) -> None:
        for src, dst in installer._jobs():
            self.assertTrue(src.exists(), f"missing source: {src}")
            self.assertTrue(str(dst).startswith(str(Path.home())), f"destination outside home: {dst}")

    def test_scripts_shipped_to_the_installed_plane_import_only_shipped_modules(self) -> None:
        """upgrade.py runs from ~/.pi/harness: a helper it imports must be installed too."""
        import ast

        scripts_dir = REPO_ROOT / "scripts"
        shipped = {src.name for src, _dst in installer._jobs() if src.parent == scripts_dir}
        for name in sorted(shipped):
            tree = ast.parse((scripts_dir / name).read_text(encoding="utf-8"))
            local: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        head = alias.name.split(".")[0]
                        if (scripts_dir / f"{head}.py").exists():
                            local.add(f"{head}.py")
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    head = module.split(".")[0]
                    if head == "scripts":
                        local.update(f"{alias.name}.py" for alias in node.names)
                    elif (scripts_dir / f"{head}.py").exists():
                        local.add(f"{head}.py")
            self.assertEqual(local - shipped, set(), f"{name} imports modules that are never installed")

    def test_sandbox_and_skill_sources_are_covered(self) -> None:
        shipped = {src for src, _dst in installer._jobs()}
        for path in sorted((REPO_ROOT / "sandbox").iterdir()):
            if path.is_file():
                self.assertIn(path, shipped, f"sandbox file not installed: {path.name}")
        for skill_dir in sorted((REPO_ROOT / "skills" / "pi-native").iterdir()):
            if skill_dir.is_dir():
                self.assertTrue((skill_dir / "SKILL.md").exists(), f"no SKILL.md in {skill_dir.name}: the installer loop skips it")


if __name__ == "__main__":
    unittest.main()
