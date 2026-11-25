"""#21: a slow dispatch must not die with the client's request; it returns a task id instead."""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import orchestrator.server as server  # noqa: E402


class AsyncDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.orch = server.Orchestrator(REPO_ROOT)

    def _patch_dispatch(self, delay: float, payload: dict) -> None:
        def fake(**kwargs):  # noqa: ANN003, ANN202 - mirrors dispatch_subtask
            time.sleep(delay)
            return payload

        patcher = mock.patch.object(server, "dispatch_subtask", fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_wait_false_returns_a_handle_immediately(self) -> None:
        self._patch_dispatch(0.6, {"ok": True, "content": "done"})
        started = time.time()
        handle = self.orch.dispatch_subagent({"agent_profile": "deep", "task_text": "x", "wait": False})
        self.assertLess(time.time() - started, 0.5, "the call must not block on the run")
        self.assertEqual(handle["status"], "running")
        task_id = handle["task_id"]
        self.assertEqual(self.orch.dispatch_result({"task_id": task_id})["status"], "running")
        deadline = time.time() + 10
        while time.time() < deadline:
            polled = self.orch.dispatch_result({"task_id": task_id})
            if polled["status"] != "running":
                break
            time.sleep(0.1)
        self.assertEqual(polled["status"], "done")
        self.assertEqual(polled["result"], {"ok": True, "content": "done"})

    def test_unknown_task_is_named_not_silent(self) -> None:
        out = self.orch.dispatch_result({"task_id": "nope"})
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "unknown_task")


if __name__ == "__main__":
    unittest.main()
