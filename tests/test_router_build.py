"""router_build must never promote an image that cannot import its entry modules."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.router_build as build  # noqa: E402


class _Result:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class PromotionTests(unittest.TestCase):
    def _run_with(self, smoke_result: tuple[bool, str], argv: list[str]) -> tuple[int, list[list[str]]]:
        calls: list[list[str]] = []

        def fake_run(cmd, timeout=1800):  # noqa: ANN001, ANN202
            calls.append(list(cmd))
            return _Result()

        with mock.patch.object(sys, "argv", ["router_build.py", *argv]), \
                mock.patch.object(build, "run", fake_run), \
                mock.patch.object(build, "smoke", lambda image: smoke_result), \
                mock.patch.object(build.shutil, "which", lambda name: "/usr/bin/docker"):
            return build.main(), calls

    def test_a_broken_image_is_never_promoted(self) -> None:
        code, calls = self._run_with((False, "SyntaxError: invalid syntax"),
                                     ["--skip-build"])
        self.assertEqual(code, 2)
        self.assertFalse([c for c in calls if c[:2] == ["docker", "tag"]], "no tag may move")

    def test_a_healthy_image_moves_local_to_prev_then_staging_to_local(self) -> None:
        code, calls = self._run_with((True, "smoke ok"), ["--skip-build"])
        self.assertEqual(code, 0)
        tags = [c for c in calls if c[:2] == ["docker", "tag"]]
        self.assertEqual(tags[0][2:4], [build.LOCAL, build.PREV])
        self.assertEqual(tags[1][2:4], [build.STAGING, build.LOCAL])

    def test_dry_run_touches_nothing(self) -> None:
        code, calls = self._run_with((True, "smoke ok"), ["--dry-run"])
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
