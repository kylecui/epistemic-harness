"""The universal gate for projects that declare none: three cheap invariants, no guessing."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GATE = REPO_ROOT / "scripts" / "gate_universal.py"


def run(cwd: Path) -> tuple[int, str]:
    proc = subprocess.run([sys.executable, str(GATE)], cwd=str(cwd), capture_output=True, text=True, timeout=120)
    return proc.returncode, proc.stdout + proc.stderr


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=60,
                   env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(cwd)})


class UniversalGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        git(self.dir, "init", "-q")
        git(self.dir, "config", "user.email", "t@example.com")
        git(self.dir, "config", "user.name", "t")

    def test_clean_repo_passes(self) -> None:
        (self.dir / "main.py").write_text("print('hi')\n", encoding="utf-8")
        git(self.dir, "add", ".")
        rc, out = run(self.dir)
        self.assertEqual(rc, 0, out)

    def test_scratch_file_fails(self) -> None:
        (self.dir / "notes.tmp").write_text("x", encoding="utf-8")
        rc, out = run(self.dir)
        self.assertEqual(rc, 1)
        self.assertIn("residue", out)

    def test_credential_in_untracked_file_fails_but_env_is_skipped(self) -> None:
        (self.dir / "config.py").write_text("KEY = 'sk-" + "a" * 24 + "'\n", encoding="utf-8")
        rc, out = run(self.dir)
        self.assertEqual(rc, 1)
        self.assertIn("secret-in-file", out)
        (self.dir / "config.py").unlink()
        (self.dir / ".env").write_text("TOKEN=sk-" + "a" * 24 + "\n", encoding="utf-8")
        self.assertEqual(run(self.dir)[0], 0, "an untracked .env is expected, not a leak")

    def test_committed_crlf_in_a_script_fails(self) -> None:
        # A repo where git does not normalise (autocrlf=false, the Linux/macOS default) and a Windows
        # editor wrote CRLF: that CRLF really does land in the index and breaks a POSIX container.
        git(self.dir, "config", "core.autocrlf", "false")
        (self.dir / "run.sh").write_bytes(b"#!/bin/sh\r\necho hi\r\n")
        git(self.dir, "add", "run.sh")
        rc, out = run(self.dir)
        self.assertEqual(rc, 1, out)
        self.assertIn("crlf-in-index", out)

    def test_outside_a_repo_it_skips_instead_of_guessing(self) -> None:
        plain = Path(tempfile.mkdtemp(prefix="gate-outside-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(plain, ignore_errors=True))
        (plain / "debug_helper.py").write_text("x = 1\n", encoding="utf-8")
        rc, out = run(plain)
        self.assertEqual(rc, 0, out)
        self.assertIn("no git repository", out)


if __name__ == "__main__":
    unittest.main()
