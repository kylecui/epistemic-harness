"""Production wiring tests: orchestrator audit_reply MCP tool (leftover #3)."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestrator.server import Orchestrator, handle_request  # noqa: E402


class AuditReplyToolTests(unittest.TestCase):
    def setUp(self):
        self.orch = Orchestrator(REPO_ROOT)

    def test_tool_declared(self):
        resp = handle_request(self.orch, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = {t["name"] for t in resp["result"]["tools"]}
        self.assertIn("audit_reply", names)

    def test_local_only_mode_never_calls_critic(self):
        with mock.patch("orchestrator.server.dispatch_subtask") as dsp:
            resp = handle_request(self.orch, {
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "audit_reply",
                           "arguments": {"text": "[L3] 方案。\n适用: 各种情况。\n反例: 因情况而异。\n",
                                         "use_critic": False}},
            })
            dsp.assert_not_called()
        payload = json.loads(resp["result"]["content"][0]["text"])
        scored = [h for h in payload["hits"] if h["decided_by"] == "deterministic"]
        self.assertTrue(scored)
        self.assertTrue(all(h["substantive"] is False for h in scored))

    def test_critic_mode_dispatches_cross_family_and_pending_is_unscored(self):
        calls = []

        def fake_dispatch(**kwargs):
            calls.append(kwargs)
            return {"content": "PENDING(gateway down)"}

        with mock.patch("orchestrator.server.dispatch_subtask", side_effect=fake_dispatch):
            with tempfile.TemporaryDirectory() as tmp:
                store = Path(tmp) / "audit.jsonl"
                from orchestrator import hollow_audit
                old = hollow_audit.HOLLOW_AUDIT_PATH
                hollow_audit.HOLLOW_AUDIT_PATH = store
                try:
                    resp = handle_request(self.orch, {
                        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "audit_reply",
                                   "arguments": {"text": "验收: p99 降至 200ms 以内。\n", "use_critic": True}},
                    })
                finally:
                    hollow_audit.HOLLOW_AUDIT_PATH = old
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["agent_profile"], "critic")
        payload = json.loads(resp["result"]["content"][0]["text"])
        self.assertTrue(all(h["decided_by"] == "pending" for h in payload["hits"]))
        self.assertIsNone(payload["hollow_rate"])  # error must not fabricate a rate


if __name__ == "__main__":
    unittest.main()
