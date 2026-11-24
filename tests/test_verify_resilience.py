"""The streamed-tree fallback: what gets sent into the container when the mount is gone."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.verify import tree_entries


class TreeEntriesTests(unittest.TestCase):
    def test_host_only_directories_are_not_sent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests" / "test_a.py").write_text("", encoding="utf-8")
            for skipped in (".venv", "__pycache__", "node_modules"):
                (root / skipped).mkdir()
                (root / skipped / "junk.py").write_text("", encoding="utf-8")
            entries = [str(p).replace("\\", "/") for p in tree_entries(root)]
        self.assertIn("tests/test_a.py", entries)
        self.assertFalse([e for e in entries if ".venv" in e or "__pycache__" in e or "node_modules" in e])

    def test_symlinks_are_skipped_so_the_stream_cannot_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root, target = Path(tmp), Path(outside) / "secret.txt"
            target.write_text("x", encoding="utf-8")
            try:
                (root / "link.txt").symlink_to(target)
            except OSError:
                self.skipTest("symlinks need privileges on this host")
            (root / "real.txt").write_text("x", encoding="utf-8")
            names = [p.name for p in tree_entries(root)]
        self.assertEqual(names, ["real.txt"])


if __name__ == "__main__":
    unittest.main()
