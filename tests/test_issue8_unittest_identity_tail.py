"""Issue #8 — an exit-gate bounce must name the test that failed.

The bounce used to carry only the last 25 lines of a check's output, so a
unittest `TypeError` raised deep inside a test hid the `ERROR: <test id>`
header that names the test. Three gate round-trips were spent re-running
before the identity `tests/test_proxy_gateway.py:135` became visible.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest

PACK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK_ROOT))

_spec = importlib.util.spec_from_file_location("eg_issue8", PACK_ROOT / "orchestrator" / "exit_gate.py")
eg = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
sys.modules["eg_issue8"] = eg
_spec.loader.exec_module(eg)

HEADER = "ERROR: test_header_strip (tests.test_proxy_gateway.ProxyTests.test_header_strip)"
TEST_ID = "tests.test_proxy_gateway.ProxyTests.test_header_strip"
TEST_FRAME = '  File "/work/tests/test_proxy_gateway.py", line 135, in test_header_strip'
RUNNER_FRAME = '  File "/usr/local/lib/python3.12/unittest/case.py", line 1342, in assertRegex'
FATAL = [
    "Traceback (most recent call last):",
    RUNNER_FRAME,
    "    if not expected_regex.search(text):",
    "TypeError: expected string or bytes-like object, got 'NoneType'",
]


def _log(header: str, filler: int, tail_lines: list[str] | None = None) -> str:
    """A unittest failure whose identity header sits `filler` lines above the tail."""
    body = [header, "-" * 70, "Traceback (most recent call last):", TEST_FRAME,
            "    self.assertRegex(value, r'x')", RUNNER_FRAME,
            "    if not expected_regex.search(text):"]
    body += [f"  context line {i}" for i in range(filler)]
    body += tail_lines if tail_lines is not None else FATAL[3:]
    return "\n".join(body)


class TailWindowTests(unittest.TestCase):
    def test_identity_header_above_the_window_is_recovered(self):
        tail = eg.build_output_tail(_log(HEADER, 40))
        self.assertIn(HEADER, tail.splitlines(), tail)

    def test_test_file_frame_is_recovered_and_repo_relative(self):
        tail = eg.build_output_tail(_log(HEADER, 40))
        self.assertIn("tests/test_proxy_gateway.py:135 in test_header_strip", tail)

    def test_exception_line_still_ends_the_tail(self):
        tail = eg.build_output_tail(_log(HEADER, 40))
        self.assertTrue(tail.splitlines()[-1].startswith("TypeError:"), tail)

    def test_non_unittest_output_is_unchanged(self):
        lines = [f"line {i}" for i in range(40)]
        self.assertEqual(eg.build_output_tail("\n".join(lines)), "\n".join(lines[-25:]))

    def test_short_log_is_unchanged(self):
        text = "\n".join([f"line {i}" for i in range(6)])
        self.assertEqual(eg.build_output_tail(text), text)

    def test_header_inside_the_window_is_not_duplicated(self):
        tail = eg.build_output_tail("\n".join([HEADER, *FATAL]))
        self.assertEqual(tail.splitlines().count(HEADER), 1, tail)

    def test_marker_announces_the_gap(self):
        tail = eg.build_output_tail(_log(HEADER, 40))
        self.assertIn("recovered from the full log", tail.splitlines()[0])

    def test_huge_output_still_fits_the_byte_budget(self):
        filler = ["x" * 200 for _ in range(600)]  # ~120 KB of check output
        tail = eg.build_output_tail(_log(HEADER, 0, filler + FATAL[3:]))
        self.assertIn(HEADER, tail)
        self.assertLessEqual(len(tail.encode("utf-8")), eg.TAIL_MAX_BYTES)

    def test_three_failures_are_all_named(self):
        log = "\n".join([
            _log("FAIL: test_a (tests.test_x.CaseA.test_a)", 30),
            _log("ERROR: test_b (tests.test_x.CaseB.test_b)", 30),
            _log("FAIL: test_c (tests.test_x.CaseC.test_c)", 30),
        ])
        tail = eg.build_output_tail(log)
        for name in ("tests.test_x.CaseA.test_a", "tests.test_x.CaseB.test_b", "tests.test_x.CaseC.test_c"):
            self.assertIn(name, tail)

    def test_last_test_frame_is_recovered_without_a_header(self):
        log = "\n".join(
            [f"  earlier output {i}" for i in range(30)]
            + ["Traceback (most recent call last):", TEST_FRAME,
               "    self.assertRegex(value, r'x')",
               "TypeError: expected string or bytes-like object, got 'NoneType'"]
            + [f"  later output {i}" for i in range(40)]
        )
        tail = eg.build_output_tail(log)
        self.assertIn("tests/test_proxy_gateway.py:135 in test_header_strip", tail)
        self.assertIn("test frame recovered", tail.splitlines()[0])
        self.assertTrue(tail.splitlines()[-1].strip().startswith("later output"), tail)

    def test_library_frame_without_a_test_is_not_invented(self):
        log = "\n".join(
            [f"  context line {i}" for i in range(40)]
            + ["Traceback (most recent call last):",
               '  File "/usr/local/lib/python3.12/site-packages/pkg/mod.py", line 9, in helper',
               "ValueError: boom"]
        )
        self.assertEqual(eg.build_output_tail(log), "\n".join(log.splitlines()[-25:]))

    def test_many_failures_still_fit_the_byte_budget(self):
        log = "\n".join(_log(f"FAIL: test_{i} (tests.test_x.C.test_{i})", 5) for i in range(300))
        log += "\n" + "\n".join("x" * 200 for _ in range(600))  # ~120 KB
        tail = eg.build_output_tail(log)
        self.assertLessEqual(len(tail.encode("utf-8")), eg.TAIL_MAX_BYTES)
        self.assertIn("tests.test_x.C.test_0", tail)
        self.assertIn("identity line(s) omitted", tail)


class BounceIdentityTests(unittest.TestCase):
    """The bounce message itself — not just the tail helper — must name the test."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_host_runner_bounce_names_the_failing_test(self):
        log = _log(HEADER, 40)
        engine = eg.ExitGateEngine(
            repo_dir=self.repo,
            checks=[eg.CheckSpec(name="unit_tests", command="run tests")],
            evidence_policy="enforce",
            gate_runner="host",
        )
        engine._run_one = types.MethodType(lambda self_, chk: (1, log, log, "host"), engine)
        decision = engine.evaluate("修好了。")
        self.assertFalse(decision.passed)
        self.assertEqual(decision.failures[0].identities, [TEST_ID])
        self.assertIn("ERROR: test_header_strip", decision.bounce_prompt)
        self.assertIn(f"failing tests {TEST_ID}", decision.bounce_prompt)

    def test_batch_docker_segment_bounce_names_the_failing_test(self):
        log = _log(HEADER, 40)
        segmented = f"\n__HARNESS_SEG_0\n{log}\n__HARNESS_RC_0=1\n"
        fake = subprocess.CompletedProcess(args=["docker"], returncode=0, stdout=segmented, stderr="")
        engine = eg.ExitGateEngine(repo_dir=self.repo, checks=[], evidence_policy="warn")

        real_run = eg.subprocess.run
        eg.subprocess.run = lambda *a, **k: fake
        try:
            failures, evidence = engine._run_batch_docker(
                [eg.CheckSpec(name="unit_tests", command="run tests")], "config"
            )
        finally:
            eg.subprocess.run = real_run

        self.assertEqual(len(failures), 1, evidence)
        self.assertEqual(failures[0].identities, [TEST_ID])
        self.assertIn(HEADER, failures[0].tail.splitlines())
        self.assertIn(HEADER, evidence[0].tail.splitlines())


if __name__ == "__main__":
    unittest.main()
