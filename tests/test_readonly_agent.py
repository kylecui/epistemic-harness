"""G13: read-only explorer — sandboxed tools, agent loop, recording, round cap."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

import httpx

PACK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK_ROOT))

os.environ.setdefault("HARNESS_TRACES_DIR", tempfile.mkdtemp(prefix="harness-test-traces-"))

from orchestrator.readonly_tools import execute_tool, read_file, grep, list_dir  # noqa: E402
from orchestrator.readonly_agent import dispatch_readonly, parse_tool_call  # noqa: E402


class ToolSandboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "a.py").write_text("X = 1\nneedle here\n", encoding="utf-8")
        (self.root / ".git").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_read_inside_root_ok(self):
        self.assertIn("needle", read_file(self.root, "src/a.py"))

    def test_escape_rejected(self):
        out = execute_tool(self.root, "read_file", {"path": "../outside.txt"})
        self.assertIn("ERROR", out)
        self.assertIn("escapes", out)

    def test_symlink_escape_rejected(self):
        outside = self.root.parent / "ro_outside_probe.txt"
        outside.write_text("secret", encoding="utf-8")
        try:
            link = self.root / "link_out"
            try:
                link.symlink_to(outside)
            except OSError:
                self.skipTest("symlinks unavailable")
            # The sandbox must refuse the escape. Via execute_tool it is an error
            # string; via read_file it raises — both are "blocked", and the
            # through-tool path is what sub-agents actually hit.
            self.assertIn("escapes", execute_tool(self.root, "read_file", {"path": "link_out"}))
            from orchestrator.readonly_tools import SandboxError
            with self.assertRaises(SandboxError):
                read_file(self.root, "link_out")
        finally:
            outside.unlink(missing_ok=True)

    def test_grep_file_line_and_cap(self):
        out = grep(self.root, "needle")
        self.assertIn("src/a.py:2", out)
        many = grep(self.root, ".", "src")
        self.assertIn("src/a.py:1", many)

    def test_list_dir(self):
        out = list_dir(self.root)
        self.assertIn("src/", out)


class ParseToolCallTests(unittest.TestCase):
    def test_fenced_json(self):
        c = parse_tool_call('looking...\n```json\n{"tool": "grep", "args": {"pattern": "x"}}\n```\n')
        self.assertEqual(c, {"tool": "grep", "args": {"pattern": "x"}})

    def test_no_tool_returns_none(self):
        self.assertIsNone(parse_tool_call("plain answer with no call"))

    def test_malformed_json_returns_none(self):
        self.assertIsNone(parse_tool_call('```json\n{"tool": "grep", broken\n```'))


class AgentLoopTests(unittest.TestCase):
    def _transport(self, script: list[str]) -> httpx.MockTransport:
        calls = {"n": 0, "bodies": []}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            calls["bodies"].append(json.loads(request.content.decode("utf-8")))
            text = script[min(calls["n"] - 1, len(script) - 1)]
            sse = (
                '{"choices":[{"delta":{"content":' + json.dumps(text) + '}}],'
                '"usage":{"prompt_tokens":1,"completion_tokens":1}}\n'
            )
            return httpx.Response(200, headers={
                "Content-Type": "text/event-stream",
                "X-Harness-Routed-Tier": "system_1",
                "X-Harness-Selected-Model": "m1",
                "X-Harness-Effort": "low",
            }, content=("data: " + sse + "data: [DONE]\n").encode("utf-8"))

        self._calls = calls
        return httpx.MockTransport(handler)

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "x.py").write_text("needle\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_tool_round_trip(self):
        script = [
            '```json\n{"tool": "grep", "args": {"pattern": "needle"}}\n```',
            "Found it at x.py:1. Done.",
        ]
        res = dispatch_readonly("find needle", self.root, task_id="t-ro",
                                transport=self._transport(script))
        self.assertEqual(res["rounds"], 2)
        self.assertEqual(res["tools_used"][0]["tool"], "grep")
        self.assertIn("x.py:1", res["content"])
        # second gateway call must contain the tool result
        second = self._calls["bodies"][1]
        self.assertIn("[tool result: grep]", second["messages"][-1]["content"])
        self.assertIn("x.py:1: needle", second["messages"][-1]["content"])
        self.assertEqual(res["selected_model"], "m1")
        self.assertEqual(res["elapsed_sec"] >= 0, True)

    def test_round_cap_stops_loop(self):
        script = ['```json\n{"tool": "grep", "args": {"pattern": "needle"}}\n```']
        res = dispatch_readonly("loop forever", self.root, task_id="t-cap", max_rounds=3,
                                transport=self._transport(script))
        self.assertEqual(res["rounds"], 3)
        self.assertEqual(len(res["tools_used"]), 3)
        self.assertIn("round cap", res["content"])

    def test_recording_has_profile_and_tools(self):
        script = ["plain answer"]
        dispatch_readonly("noop", self.root, task_id="t-rec", category="exploration",
                          transport=self._transport(script))
        trace = Path(os.environ["HARNESS_TRACES_DIR"]) / "dispatches.jsonl"
        rec = json.loads(trace.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(rec["profile"], "explorer-ro")
        self.assertEqual(rec["category"], "exploration")
        self.assertIn("tools_used", rec)


if __name__ == "__main__":
    unittest.main()
