"""#24: a transient mount error is retried once, then named; a missing path stays fatal."""
from __future__ import annotations

import errno
import unittest

from orchestrator.fsretry import MountUnhealthy, is_transient, with_retry


class FsRetryTests(unittest.TestCase):
    def test_enomem_is_retried_then_named(self) -> None:
        calls = []

        def flaky() -> str:
            calls.append(1)
            raise OSError(errno.ENOMEM, "Cannot allocate memory")

        with self.assertRaises(MountUnhealthy) as caught:
            with_retry(flaky, attempts=2, delay=0)
        self.assertEqual(len(calls), 2, "exactly one retry, not a loop")
        self.assertIn("restart Docker Desktop", str(caught.exception))

    def test_a_transient_error_that_clears_is_transparent(self) -> None:
        calls = []

        def once() -> str:
            calls.append(1)
            if len(calls) == 1:
                raise OSError(errno.EIO, "Input/output error")
            return "ok"

        self.assertEqual(with_retry(once, attempts=2, delay=0), "ok")

    def test_a_missing_path_is_not_retried(self) -> None:
        calls = []

        def missing() -> None:
            calls.append(1)
            raise OSError(errno.ENOENT, "No such file or directory")

        with self.assertRaises(OSError):
            with_retry(missing, attempts=3, delay=0)
        self.assertEqual(len(calls), 1)

    def test_classification(self) -> None:
        self.assertTrue(is_transient(OSError(errno.ENOMEM, "x")))
        self.assertFalse(is_transient(OSError(errno.ENOENT, "x")))
        self.assertFalse(is_transient(ValueError("x")))


if __name__ == "__main__":
    unittest.main()
