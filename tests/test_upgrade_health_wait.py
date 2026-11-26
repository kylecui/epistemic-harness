"""Switching before the new backend is healthy must be refused, not silently reverted."""
from __future__ import annotations

import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.upgrade as upgrade  # noqa: E402


class HealthyGateTests(unittest.TestCase):
    def test_a_healthy_backend_returns_true_immediately(self) -> None:
        with mock.patch.object(upgrade, "gate_status", lambda *a, **k: {"healthy": {"green": True}}):
            self.assertTrue(upgrade.wait_until_healthy("green", timeout=1, interval=0))

    def test_it_waits_then_succeeds_when_the_backend_catches_up(self) -> None:
        calls = {"n": 0}

        def flaky(*_a, **_k):
            calls["n"] += 1
            return {"healthy": {"green": calls["n"] >= 2}}

        with mock.patch.object(upgrade, "gate_status", flaky):
            self.assertTrue(upgrade.wait_until_healthy("green", timeout=5, interval=0))
        self.assertGreaterEqual(calls["n"], 2)

    def test_it_gives_up_instead_of_switching_blind(self) -> None:
        with mock.patch.object(upgrade, "gate_status", lambda *a, **k: {"healthy": {"green": False}}):
            self.assertFalse(upgrade.wait_until_healthy("green", timeout=0.05, interval=0.01))

    def test_a_gate_that_is_not_answering_is_not_mistaken_for_health(self) -> None:
        with mock.patch.object(upgrade, "gate_status", lambda *a, **k: None):
            self.assertFalse(upgrade.wait_until_healthy("green", timeout=0.05, interval=0.01))


if __name__ == "__main__":
    unittest.main()
