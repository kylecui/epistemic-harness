"""Tests for the unified HTTP backend (gateway + MCP-over-HTTP bridges)."""

import json
from pathlib import Path
import sys
import unittest

from starlette.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import harness_backend  # noqa: E402


class TestHttpBridge(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(harness_backend.parent)

    def test_gateway_health_still_served_at_root(self) -> None:
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_epistemic_tools_list_over_http(self) -> None:
        resp = self.client.post("/mcp/epistemic", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(resp.status_code, 200)
        tools = resp.json()["result"]["tools"]
        names = {t["name"] for t in tools}
        self.assertIn("query_l1", names)
        self.assertIn("audit_dag", names)
        self.assertEqual(len(tools), 7)

    def test_orchestrator_classify_over_http(self) -> None:
        resp = self.client.post(
            "/mcp/orchestrator",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "classify_task", "arguments": {"task_text": "把 MAX_RETRY_COUNT 转成 camelCase，直接给我结果"}},
            },
        )
        self.assertEqual(resp.status_code, 200)
        payload = json.loads(resp.json()["result"]["content"][0]["text"])
        self.assertEqual(payload["tier"], "system_0")

    def test_bias_scan_over_http(self) -> None:
        resp = self.client.post(
            "/mcp/orchestrator",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "bias_scan", "arguments": {"text": "这个方案绝对没问题"}},
            },
        )
        payload = json.loads(resp.json()["result"]["content"][0]["text"])
        self.assertIn("BIAS-OVERCONFIDENCE", [m["bias_id"] for m in payload["matches"]])

    def test_get_returns_405_with_allow_header(self) -> None:
        resp = self.client.get("/mcp/epistemic")
        self.assertEqual(resp.status_code, 405)
        self.assertEqual(resp.headers["allow"], "POST")
        resp2 = self.client.get("/mcp/orchestrator")
        self.assertEqual(resp2.status_code, 405)

    def test_notification_returns_202(self) -> None:
        resp = self.client.post("/mcp/epistemic", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual(resp.status_code, 202)

    def test_mcp_health_endpoint(self) -> None:
        resp = self.client.get("/mcp/health")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["epistemic_tools"] >= 7)


if __name__ == "__main__":
    unittest.main()
