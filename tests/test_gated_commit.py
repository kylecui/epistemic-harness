"""gated_commit commits what the caller staged, and sweeps only when nothing is staged (#25)."""
from __future__ import annotations

import sys
import unittest
from unittest import mock

from scripts import gated_commit


class _Result:
    def __init__(self, stdout: str = "", returncode: int = 0) -> None:
        self.stdout, self.stderr, self.returncode = stdout, "", returncode


def _run_gated(staged_paths: list[str]) -> list[list[str]]:
    commands: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # noqa: ANN001, ANN202 - mirrors subprocess.run
        commands.append(list(cmd))
        if cmd[:3] == ["git", "diff", "--cached"]:
            return _Result("\n".join(staged_paths))
        return _Result("[main abc1234] test commit")

    with mock.patch.object(gated_commit, "run", fake_run), \
            mock.patch.object(sys, "argv", ["gated_commit.py", "-m", "test", "--skip-tests"]):
        assert gated_commit.main() == 0
    return commands


class StagingModeTests(unittest.TestCase):
    def test_a_staged_call_never_sweeps_the_tree(self) -> None:
        commands = _run_gated(["scripts/verify.py", "tests/test_foo.py"])
        self.assertNotIn(["git", "add", "-A"], commands)

    def test_an_unstaged_call_still_sweeps(self) -> None:
        self.assertIn(["git", "add", "-A"], _run_gated([]))


if __name__ == "__main__":
    unittest.main()
