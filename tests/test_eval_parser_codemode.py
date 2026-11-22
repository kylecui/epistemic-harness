"""Parser regression: MCP tools invoked via codemode must still be counted.

Real pi JSON streams record MCP tool usage as `codemode` toolCalls whose script
source references `mcp__epistemic_harness__<tool>` and whose console output
embeds the audit JSON with prose prefixes. parse_pi_jsonl_events must recover
both (found live 2026-11-22: every real-model golden run failed with
cap=None because toolName was 'codemode').
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evals.run_evals import parse_pi_jsonl_events  # noqa: E402


def _stream(events: list[dict]) -> bytes:
    return ("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n").encode("utf-8")


class CodemodeMcpParseTests(unittest.TestCase):
    def test_codemode_tool_names_and_embedded_audit_recovered(self):
        audit = {"total_l5_claims": 1, "overall_confidence_cap": "L3",
                 "converge_allowed": True, "claims": []}
        events = [
            {"type": "toolCall", "id": "c1", "name": "codemode",
             "arguments": {"code": "const r = await tools.mcp__epistemic_harness__query_l1({query:'cap'});"
                                   "return r;"}},
            {"type": "tool_execution_start", "toolName": "codemode", "toolCallId": "c2"},
            {"type": "tool_execution_end", "toolName": "codemode", "toolCallId": "c2",
             "result": {"content": [
                 {"type": "text", "text": "Script completed\nWall time 0.2 seconds\nOutput:\n"},
                 {"type": "text", "text": "==> text 1/1 <==\n" + json.dumps(audit, ensure_ascii=False)},
             ]}, "isError": False},
            {"type": "assistant_message", "message": {"role": "assistant",
                                                       "content": "[Tier: Structured | Mode: Converge | Cap: L3]\n结论"}},
        ]
        trace = parse_pi_jsonl_events("TC-X", _stream(events), 0, "")
        self.assertIn("codemode", trace.tool_calls)
        self.assertIn("query_l1", trace.tool_calls)
        self.assertEqual(len(trace.audit_dag_results), 1)
        self.assertEqual(trace.latest_audit["overall_confidence_cap"], "L3")

    def test_plain_toolcalls_still_parsed(self):
        events = [
            {"type": "assistant_message", "message": {"role": "assistant", "content": [
                {"type": "toolCall", "name": "bash", "arguments": {"command": "ls"}},
                {"type": "text", "text": "done"},
            ]}},
        ]
        trace = parse_pi_jsonl_events("TC-Y", _stream(events), 0, "")
        self.assertIn("bash", trace.tool_calls)


if __name__ == "__main__":
    unittest.main()
