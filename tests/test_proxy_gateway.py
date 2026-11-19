import json
from pathlib import Path
import sys
import unittest

from fastapi.testclient import TestClient
import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from proxy_gateway.app import create_app
from proxy_gateway.policy import decide_routing


class TestProxyGateway(unittest.TestCase):
    def test_f05_clamps_reasoning_effort_by_task_fingerprint(self) -> None:
        d0 = decide_routing([{"role": "user", "content": "把 MAX_RETRY_COUNT 转成 camelCase JSON key，直接给我结果"}])
        self.assertEqual(d0.tier, "system_0")
        self.assertEqual(d0.anthropic_budget, 0)

        d15 = decide_routing([{"role": "user", "content": "帮我分析一下这个 5 人初创团队的后端架构选型"}])
        self.assertEqual(d15.tier, "system_1_5")
        self.assertEqual(d15.openai_effort, "medium")

        d2 = decide_routing([{"role": "user", "content": "请用 CAP 定理形式化证明跨机房网络分区下为何无法同时满足 C 和 A"}])
        self.assertEqual(d2.tier, "system_2")
        self.assertEqual(d2.openai_effort, "high")

        dh = decide_routing(
            [{"role": "user", "content": "请用 CAP 定理分析"}],
            headers={"X-Harness-Tier": "system_0"},
        )
        self.assertEqual(dh.tier, "system_0")

    def test_f03_streaming_thrashing_auto_recovers_with_low_reasoning_openai(self) -> None:
        """When stream #1 thrashes (4 pivots), gateway aborts and seamlessly continues at reasoning_effort='low'."""
        captured_efforts: list[str] = []

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode("utf-8"))
            captured_efforts.append(body.get("reasoning_effort", ""))
            if len(captured_efforts) == 1:
                sse_chunks = [
                    'data: {"id":"1","choices":[{"delta":{"reasoning_content":"Aha! Wait, hold on..."}}]}\n\n',
                    'data: {"id":"1","choices":[{"delta":{"reasoning_content":"Actually, wait... let me reconsider."}}]}\n\n',
                    'data: {"id":"1","choices":[{"delta":{"reasoning_content":"On second thought, wait, but maybe not."}}]}\n\n',
                    'data: {"id":"1","choices":[{"delta":{"reasoning_content":"should_never_reach_after_abort"}}]}\n\n',
                    'data: [DONE]\n\n',
                ]
                return httpx.Response(200, headers={"content-type": "text/event-stream"}, content="".join(sse_chunks).encode("utf-8"))
            # Recovery call at low reasoning!
            rec_chunks = [
                'data: {"id":"2","choices":[{"delta":{"content":"Recovered seamlessly: calling L2 trace tool."}}]}\n\n',
                'data: [DONE]\n\n',
            ]
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content="".join(rec_chunks).encode("utf-8"))

        app = create_app(openai_upstream="https://mock.openai.local/v1", transport=httpx.MockTransport(mock_handler))
        client = TestClient(app)
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-reasoner",
                "reasoning_effort": "high",
                "stream": True,
                "messages": [{"role": "user", "content": "线上 API 延迟飙升但没给 Trace，分析一下"}],
            },
        )
        self.assertEqual(resp.status_code, 200)
        # First call clamped high -> medium; auto-recovery call automatically downgraded to low!
        self.assertEqual(captured_efforts, ["medium", "low"])
        self.assertIn("Recovered seamlessly: calling L2 trace tool.", resp.text)
        self.assertNotIn("should_never_reach_after_abort", resp.text)

    def test_anthropic_thinking_budget_and_seamless_recovery(self) -> None:
        captured_thinking: list[dict] = []

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode("utf-8"))
            captured_thinking.append(body.get("thinking", {}))
            if len(captured_thinking) == 1:
                sse = (
                    'event: content_block_delta\n'
                    'data: {"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"等等不对，不对等等，话又说回来..." }}\n\n'
                    'event: content_block_delta\n'
                    'data: {"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"should_be_aborted" }}\n\n'
                )
                return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse.encode("utf-8"))
            rec_sse = (
                'event: content_block_delta\n'
                'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Anthropic seamless continuation"}}\n\n'
                'event: message_stop\ndata: {"type":"message_stop"}\n\n'
            )
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=rec_sse.encode("utf-8"))

        app = create_app(anthropic_upstream="https://mock.anthropic.local", transport=httpx.MockTransport(mock_handler))
        client = TestClient(app)
        resp = client.post(
            "/anthropic/v1/messages",
            headers={"X-Harness-Tier": "system_1"},
            json={"model": "claude-test", "stream": True, "messages": [{"role": "user", "content": "快速初筛一下"}]},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(captured_thinking[0], {"type": "enabled", "budget_tokens": 2048})
        self.assertEqual(captured_thinking[1], {"type": "disabled"})
        self.assertIn("Anthropic seamless continuation", resp.text)
        self.assertNotIn("should_be_aborted", resp.text)

    def test_thinking_in_english_system_injection(self) -> None:
        from proxy_gateway.policy import inject_thinking_language_openai, inject_thinking_language_anthropic

        oa = inject_thinking_language_openai({"messages": [{"role": "user", "content": "分析架构"}]})
        self.assertEqual(oa["messages"][0]["role"], "system")
        self.assertIn("Conduct internal reasoning/thinking in concise English", oa["messages"][0]["content"])
        an = inject_thinking_language_anthropic({"messages": [{"role": "user", "content": "分析架构"}]})
        self.assertIn("Conduct internal reasoning/thinking in concise English", an["system"])


if __name__ == "__main__":
    unittest.main()
