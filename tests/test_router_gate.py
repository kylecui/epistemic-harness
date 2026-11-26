"""router-gate: parse backends, pick targets, and fail over in one retry."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.router_gate as gate  # noqa: E402


class BackendParsingTests(unittest.TestCase):
    def test_named_backends_are_parsed_in_order(self) -> None:
        parsed = gate.parse_backends("blue=http://b:8787, green=http://g:8787")
        self.assertEqual([name for name, _ in parsed], ["blue", "green"])
        self.assertEqual(parsed[1][1].hostname, "g")

    def test_junk_entries_are_skipped_instead_of_crashing(self) -> None:
        self.assertEqual(gate.parse_backends("nonsense,,x=http://h:1"), [("x", gate.urllib.parse.urlsplit("http://h:1"))])


class TargetSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig = (list(gate.BACKENDS), dict(gate.STATE))
        gate.BACKENDS[:] = gate.parse_backends("blue=http://b:1,green=http://g:1")

    def tearDown(self) -> None:
        gate.BACKENDS[:] = self._orig[0]
        gate.STATE.clear()
        gate.STATE.update(self._orig[1])

    def test_the_active_backend_is_tried_first(self) -> None:
        gate.STATE.update({"active": "green", "healthy": {"blue": True, "green": True}})
        self.assertEqual(gate.pick_targets()[0], "green")

    def test_only_healthy_backends_are_offered_as_a_retry(self) -> None:
        gate.STATE.update({"active": "green", "healthy": {"blue": True, "green": False}})
        self.assertEqual(gate.pick_targets(), ["green", "blue"])
        gate.STATE.update({"healthy": {"blue": False, "green": False}})
        self.assertEqual(gate.pick_targets(), ["green"], "an unhealthy spare must not be retried blindly")


if __name__ == "__main__":
    unittest.main()
