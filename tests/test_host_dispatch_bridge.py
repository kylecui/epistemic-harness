"""Issue #7: dispatch must reach host worktrees without mounting the host.

Acceptance from docs/ISSUE-PLAN-2026-11-25.md (B3):
  1. a dispatch against a host path succeeds through the host agent and records runner=host;
  2. with the agent stopped the error is host_dispatch_unavailable plus the command to start it;
  3. no new mount appears in docker-compose.yml.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest import mock

PACK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK_ROOT))

os.environ.setdefault("HARNESS_TRACES_DIR", tempfile.mkdtemp(prefix="harness-test-traces-"))

from orchestrator import host_bridge  # noqa: E402
from orchestrator.server import Orchestrator, handle_request  # noqa: E402
from scripts import host_dispatch  # noqa: E402


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class HostAgentCase(unittest.TestCase):
    """A real host agent on a real loopback port; only the dispatch impls are stubbed."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workdir = Path(self._tmp.name)
        (self.workdir / "src").mkdir()
        (self.workdir / "src" / "a.py").write_text("needle here\n", encoding="utf-8")

        self.calls: list[dict] = []

        def fake_readonly(**kwargs):
            self.calls.append(kwargs)
            return {"agent_profile": "explorer-ro", "task_id": kwargs["task_id"],
                    "content": "found needle at src/a.py:1", "tools_used": [], "rounds": 1,
                    "elapsed_sec": 0.01, "bias_scan": {"matches": []}, "category": "exploration",
                    "runner": kwargs.get("runner"), "via": kwargs.get("via")}

        def fake_tooled(**kwargs):
            self.calls.append(kwargs)
            return {"profile": kwargs["profile"], "status": "ok", "workdir": kwargs["workdir"],
                    "exit_code": 0, "stdout": "patched", "stderr": "", "duration_sec": 0.01}

        self.service = host_dispatch.HostDispatchService(
            repo_root=PACK_ROOT, readonly_fn=fake_readonly, tooled_fn=fake_tooled)
        self.server = host_dispatch.build_server("127.0.0.1", 0, self.service)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        self._env = mock.patch.dict(os.environ, {
            "HARNESS_HOST_DISPATCH_URL": f"http://127.0.0.1:{self.port}",
            "HARNESS_PLANE": "container",  # pretend the orchestrator sits in the backend
        }, clear=False)
        self._env.start()
        os.environ.pop("HARNESS_HOST_DISPATCH_TOKEN", None)
        # One filesystem serves both "planes" in-process, so the container's invisibility of
        # host paths is simulated at its single seam: the visibility probe.
        self._invisible = mock.patch("orchestrator.host_bridge.local_dir_usable", return_value=False)
        self._invisible.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self._invisible.stop()
        self._env.stop()
        self._tmp.cleanup()


class TestReadonlyThroughHostAgent(HostAgentCase):
    def test_host_path_dispatches_and_records_runner_host(self) -> None:
        # the workdir exists on this machine, but the container plane cannot see it — that is
        # exactly the failure in issue #7, so the visibility probe is what the fix hinges on
        res = host_bridge.dispatch_readonly_routed(
            "find the needle", str(self.workdir), task_id="ro-host", max_rounds=2)
        self.assertEqual(res["runner"], "host")
        self.assertEqual(res["via"], "host_dispatch")
        self.assertEqual(res["content"], "found needle at src/a.py:1")
        self.assertEqual(self.calls[0]["workdir"], self.workdir)
        self.assertIn("not a directory", res["plane_reason"])

    def test_in_container_plane_routes_because_path_is_invisible(self) -> None:
        # the container plane cannot see D:\...; the decision must name that, not raise
        choice, reason = host_bridge.plan_plane("readonly", "D:/MyWorkSpaces/tmp/does-not-exist")
        self.assertEqual(choice, "host")
        self.assertIn("not a directory", reason)

    def test_readable_local_path_runs_in_process_on_the_host_plane(self) -> None:
        with mock.patch.dict(os.environ, {"HARNESS_PLANE": "host"}, clear=False),              mock.patch("orchestrator.host_bridge.local_dir_usable", return_value=True),              mock.patch("orchestrator.readonly_agent.dispatch_readonly",
                        return_value={"agent_profile": "explorer-ro", "content": "local"}) as local:
            res = host_bridge.dispatch_readonly_routed("q", str(self.workdir))
        self.assertTrue(local.called, "a readable workdir must not be forwarded")
        self.assertEqual(res["runner"], "host")       # this process IS the host plane
        self.assertEqual(res["via"], "in-process")
        self.assertEqual(self.calls, [])


class TestSleepingAgentNamesTheBoundary(unittest.TestCase):
    def test_agent_down_returns_host_dispatch_unavailable_with_start_command(self) -> None:
        dead = f"http://127.0.0.1:{_free_port()}"
        with mock.patch.dict(os.environ, {"HARNESS_HOST_DISPATCH_URL": dead,
                                          "HARNESS_PLANE": "container"}, clear=False):
            res = host_bridge.dispatch_readonly_routed("q", "D:/no/such/worktree")
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "host_dispatch_unavailable")
        self.assertEqual(res["host_dispatch_url"], dead)
        self.assertIn("python scripts/host_dispatch.py", res["remedy"])
        self.assertIn("container", res["boundary"])
        # never a raw ENOENT leaking out as if the path were the problem
        self.assertNotIn("ENOENT", json.dumps(res))
        self.assertNotIn("Errno 2", json.dumps(res))

    def test_probe_is_none_when_agent_is_absent(self) -> None:
        self.assertIsNone(host_bridge.probe(timeout=0.3, url=f"http://127.0.0.1:{_free_port()}"))


class TestTooledThroughHostAgent(HostAgentCase):
    def test_tooled_in_container_goes_to_host(self) -> None:
        res = host_bridge.dispatch_tooled_routed(
            "implement the parser", workdir=str(PACK_ROOT), profile="coder")
        self.assertEqual(res["runner"], "host")
        self.assertEqual(res["via"], "host_dispatch")
        self.assertEqual(res["status"], "ok")
        self.assertEqual(self.calls[0]["profile"], "coder")

    def test_tooled_without_pi_binary_hands_off(self) -> None:
        with mock.patch.dict(os.environ, {"HARNESS_PLANE": "host"}, clear=False), \
             mock.patch("orchestrator.host_bridge.pi_binary", return_value=None):
            choice, reason = host_bridge.plan_plane("tooled", str(PACK_ROOT))
        self.assertEqual(choice, "host")
        self.assertIn("pi", reason)

    def test_workdir_outside_allowed_roots_is_rejected_with_roots_listed(self) -> None:
        with tempfile.TemporaryDirectory() as outside:
            with mock.patch.dict(os.environ, {"HARNESS_TOOLED_ROOTS": ""}, clear=False):
                res = host_bridge.dispatch_tooled_routed("x", workdir=outside)
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "workdir_rejected")
        self.assertIn("allowed roots", res["message"])


class TestAgentAuth(HostAgentCase):
    def test_token_required_when_configured(self) -> None:
        service = host_dispatch.HostDispatchService(repo_root=PACK_ROOT, token="s3cret",
                                                    readonly_fn=lambda **k: {"ok": True})
        server = host_dispatch.build_server("127.0.0.1", 0, service)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with mock.patch.dict(os.environ,
                                 {"HARNESS_HOST_DISPATCH_URL": f"http://127.0.0.1:{port}"},
                                 clear=False):
                os.environ.pop("HARNESS_HOST_DISPATCH_TOKEN", None)
                denied = host_bridge.dispatch_readonly_routed("q", str(self.workdir))
                self.assertEqual(denied["error"], "host_dispatch_http_error")
                self.assertEqual(denied["http_status"], 401)
                os.environ["HARNESS_HOST_DISPATCH_TOKEN"] = "s3cret"
                allowed = host_bridge.dispatch_readonly_routed("q", str(self.workdir))
                self.assertEqual(allowed["runner"], "host")
                self.assertFalse(allowed.get("ok") is False, allowed)
        finally:
            os.environ.pop("HARNESS_HOST_DISPATCH_TOKEN", None)
            server.shutdown()
            server.server_close()


class TestMcpWiring(HostAgentCase):
    def test_mcp_tool_call_carries_runner_and_plane_reason(self) -> None:
        orch = Orchestrator(PACK_ROOT)
        resp = handle_request(orch, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                     "params": {
            "name": "dispatch_readonly",
            "arguments": {"task_text": "find needle", "workdir": str(self.workdir),
                          "task_id": "ro-mcp"},
        }})
        payload = json.loads(resp["result"]["content"][0]["text"])
        self.assertEqual(payload["runner"], "host")
        self.assertEqual(payload["via"], "host_dispatch")
        self.assertIn("report", payload)  # the interim report layer still wraps every dispatch

    def test_mcp_tooled_tool_call_uses_the_bridge(self) -> None:
        orch = Orchestrator(PACK_ROOT)
        resp = handle_request(orch, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "dispatch_tooled",
            "arguments": {"task_text": "implement x", "workdir": str(PACK_ROOT)},
        }})
        payload = json.loads(resp["result"]["content"][0]["text"])
        self.assertEqual(payload["runner"], "host")
        self.assertEqual(payload["status"], "ok")

    def test_forced_local_runner_skips_the_bridge(self) -> None:
        orch = Orchestrator(PACK_ROOT)
        with mock.patch("orchestrator.tooled.dispatch_tooled",
                        return_value={"status": "ok", "stdout": "local", "exit_code": 0}) as local:
            resp = handle_request(orch, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                "name": "dispatch_tooled",
                "arguments": {"task_text": "x", "workdir": str(PACK_ROOT), "runner": "local"},
            }})
        payload = json.loads(resp["result"]["content"][0]["text"])
        self.assertTrue(local.called)
        self.assertEqual(payload["via"], "in-process")
        self.assertEqual(self.calls, [])


class TestNoNewMountInCompose(unittest.TestCase):
    """The fix must not buy host access with a bind mount (issue #7's stated constraint)."""

    def setUp(self) -> None:
        self.compose = (PACK_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    def test_backend_mounts_are_repo_relative_only(self) -> None:
        backend = self.compose.split("harness-backend:", 1)[1].split("\n  verify:", 1)[0]
        sources = [line.strip()[2:].split(":", 1)[0]
                   for line in backend.splitlines() if line.strip().startswith("- ./")]
        self.assertTrue(sources, "expected the declared bind mounts to be parsed")
        for src in sources:
            self.assertTrue(src.startswith("."), f"unexpected absolute host mount: {src}")
            self.assertNotIn("\\", src, f"windows host path leaked into compose: {src}")
            self.assertNotIn("MyWorkSpaces", src)
            self.assertFalse(Path(src).is_absolute() and not src.startswith("./"),
                             f"mount escapes the repo: {src}")

    def test_bridge_is_reached_by_url_not_by_mount(self) -> None:
        self.assertIn("HARNESS_HOST_DISPATCH_URL", self.compose)
        self.assertIn("host.docker.internal", self.compose)
        self.assertIn("host-gateway", self.compose)


if __name__ == "__main__":
    unittest.main()
