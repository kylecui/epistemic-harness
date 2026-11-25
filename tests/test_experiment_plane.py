"""#13: the campaign can run on the Linux plane, and says so in every record."""
from __future__ import annotations

import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class ExperimentPlaneTests(unittest.TestCase):
    def test_the_gateway_url_comes_from_the_environment(self) -> None:
        import experiments.judge as judge
        import experiments.runner as runner

        with mock.patch.dict(os.environ, {"HARNESS_LAB_GATEWAY": "http://harness-backend-lab:8787"}):
            runner = importlib.reload(runner)
            judge = importlib.reload(judge)
            self.assertEqual(runner.LAB_GATEWAY, "http://harness-backend-lab:8787")
            self.assertEqual(judge.LAB_GATEWAY, "http://harness-backend-lab:8787")
        importlib.reload(runner)
        importlib.reload(judge)

    def test_the_lab_compose_declares_a_container_runner(self) -> None:
        compose = (ROOT / "docker-compose.lab.yml").read_text(encoding="utf-8")
        self.assertIn("lab-runner:", compose)
        self.assertIn("HARNESS_RUNNER: container", compose)
        self.assertIn("HARNESS_LAB_GATEWAY:", compose)


if __name__ == "__main__":
    unittest.main()
