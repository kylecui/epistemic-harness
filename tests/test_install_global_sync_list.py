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


if __name__ == "__main__":
    unittest.main()
