"""The upgrade must never recreate the backend that is serving, and never promote a broken image."""
from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.upgrade as upgrade  # noqa: E402


class UpgradePlanTests(unittest.TestCase):
    def test_solo_mode_recreates_the_single_service(self) -> None:
        plan = upgrade.upgrade_plan(None)
        self.assertEqual(len(plan), 1)
        self.assertIn("--profile", plan[0])
        self.assertIn("harness-backend", plan[0])

    def test_ha_mode_upgrades_the_idle_side_then_switches(self) -> None:
        plan = upgrade.upgrade_plan({"active": "blue"})
        recreate, switch = plan
        self.assertIn("backend-green", recreate, "must never recreate the serving side")
        self.assertIn("--force-recreate", recreate)
        self.assertEqual(switch[-2:], ["switch", "green"])

    def test_the_other_direction_mirrors(self) -> None:
        plan = upgrade.upgrade_plan({"active": "green"})
        self.assertIn("backend-blue", plan[0])
        self.assertEqual(plan[1][-2:], ["switch", "blue"])

    def test_the_plan_always_uses_the_ha_overlay_in_ha_mode(self) -> None:
        plan = upgrade.upgrade_plan({"active": "blue"})
        self.assertIn(upgrade.HA_OVERLAY, plan[0])


if __name__ == "__main__":
    unittest.main()
