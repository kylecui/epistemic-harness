"""Tests for (1) deepseek-first routing chains, (2) X-Harness-Agent-Id task routing,
and (3) the output-contract tier-tag validator/injector."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

from fastapi.testclient import TestClient
import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from proxy_gateway.app import create_app
from proxy_gateway.quota_manager import QuotaManager
from proxy_gateway.response_guard import (
    build_tier_tag,
    detect_mode,
    ensure_text_tag,
    guard_anthropic_content,
    guard_openai_message,
    guard_openai_stream_delta,
)


class TestChainPriorityContract(unittest.TestCase):
    def test_zhipu_head_opencode_tail_for_all_tiers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            qm = QuotaManager(REPO_ROOT / "proxy_gateway" / "quota_policy.yaml", Path(tmp) / "q.db")
            for tier in ("system_0", "system_1", "system_1_5", "system_2", "system_2_plus"):
                chain = qm.routing_chains[tier]
                # L4 decision (2026-11-24): sub-agents prefer zhipu > kimi > copilot > google;
                # opencode is the LAST-resort fallback. The main agent still reaches it first
                # by passing the model explicitly as requested_model.
                self.assertTrue(chain[0].startswith("zhipu"), msg=f"{tier} must start with zhipu: {chain}")
                self.assertEqual(chain[-1], "opencode-deepseek-v4.1-flash",
                                 msg=f"{tier} must end with the opencode fallback: {chain}")
            # Agent profiles are loaded: pin tier (reasoning intensity) only,
            # model selection stays with the local dynamic router.
            self.assertIn("coder", qm.agent_profiles)
            self.assertNotIn("model", qm.agent_profiles["coder"])
            self.assertEqual(qm.agent_profiles["coder"]["tier"], "system_1_5")
            self.assertEqual(qm.agent_profiles["critic"]["tier"], "system_2_plus")


class TestAgentProfileRouting(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.qm = QuotaManager(
            REPO_ROOT / "proxy_gateway" / "quota_policy.yaml", Path(self.tmp.name) / "q.db"
        )
        self.now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)  # all pools off-peak

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _app_with_capture(self, captured: dict):
        async def mock_handler(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content.decode("utf-8")))
            return httpx.Response(
                200,
                json={
                    "id": "ok",
                    "choices": [{"message": {"role": "assistant", "content": "结果是 42"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                },
            )

        return create_app(
            openai_upstream="https://mock.local/v1",
            transport=httpx.MockTransport(mock_handler),
            quota_manager=self.qm,
            now_provider=lambda: self.now,
        )

    def test_coder_profile_sets_tier_and_leaves_model_to_router(self) -> None:
        captured: dict = {}
        client = TestClient(self._app_with_capture(captured))
        resp = client.post(
            "/v1/chat/completions",
            headers={"X-Harness-Agent-Id": "coder"},
            json={"stream": False, "messages": [{"role": "user", "content": "重构这个函数"}]},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["x-harness-routed-tier"], "system_1_5")
        # No model pin: local router picks the chain head (zhipu, L4 priority 2026-11-24)
        self.assertTrue(captured["model"].startswith("glm-"), captured["model"])
        self.assertEqual(captured["reasoning_effort"], "medium")  # system_1_5 effort

    def test_explorer_profile_uses_lightweight_tier(self) -> None:
        captured: dict = {}
        client = TestClient(self._app_with_capture(captured))
        resp = client.post(
            "/v1/chat/completions",
            headers={"X-Harness-Agent-Id": "explorer"},
            json={"stream": False, "messages": [{"role": "user", "content": "快速列一下相关文件"}]},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["x-harness-routed-tier"], "system_1")
        self.assertTrue(captured["model"].startswith("glm-"), captured["model"])
        self.assertEqual(captured["reasoning_effort"], "low")

    def test_explicit_tier_header_overrides_agent_profile(self) -> None:
        captured: dict = {}
        client = TestClient(self._app_with_capture(captured))
        resp = client.post(
            "/v1/chat/completions",
            headers={"X-Harness-Agent-Id": "coder", "X-Harness-Tier": "system_2"},
            json={"stream": False, "messages": [{"role": "user", "content": "做形式化证明"}]},
        )
        self.assertEqual(resp.status_code, 200)
        # Tier from explicit header wins; model still chosen by local router (zhipu head)
        self.assertEqual(resp.headers["x-harness-routed-tier"], "system_2")
        self.assertTrue(captured["model"].startswith("glm-"), captured["model"])
        self.assertEqual(captured["reasoning_effort"], "high")

    def test_unknown_agent_id_falls_back_to_fingerprint(self) -> None:
        captured: dict = {}
        client = TestClient(self._app_with_capture(captured))
        resp = client.post(
            "/v1/chat/completions",
            headers={"X-Harness-Agent-Id": "no-such-agent"},
            json={"stream": False, "messages": [{"role": "user", "content": "分析一下架构选型"}]},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["x-harness-routed-tier"], "system_1_5")  # default fingerprint


class TestResponseTagGuard(unittest.TestCase):
    def test_ensure_text_tag_injects_only_when_missing(self) -> None:
        tag = build_tier_tag("system_1_5", "Converge")
        new_text, injected = ensure_text_tag("结果是 42", tag)
        self.assertTrue(injected)
        self.assertTrue(new_text.startswith(tag))

        compliant = "[Tier: Structured Analysis (Tier 1.5) | Mode: Converge]\n\n结果是 42"
        new_text2, injected2 = ensure_text_tag(compliant, tag)
        self.assertFalse(injected2)
        self.assertEqual(new_text2, compliant)

    def test_detect_mode_defaults(self) -> None:
        self.assertEqual(detect_mode("帮我收敛一下结论", "system_1"), "Converge")
        self.assertEqual(detect_mode("随便聊聊", "system_0"), "Explore")
        self.assertEqual(detect_mode("随便聊聊", "system_2"), "Converge")

    def test_guard_openai_message_and_stream_delta(self) -> None:
        tag = build_tier_tag("system_0", "Explore")
        data = {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
        self.assertTrue(guard_openai_message(data, tag))
        self.assertTrue(data["choices"][0]["message"]["content"].startswith(tag))

        compliant = {"choices": [{"message": {"role": "assistant", "content": "[Tier: x] ok"}}]}
        self.assertFalse(guard_openai_message(compliant, tag))

        delta: dict = {}
        self.assertFalse(guard_openai_stream_delta(delta, tag))  # empty content
        delta = {"content": "ok"}
        self.assertTrue(guard_openai_stream_delta(delta, tag))
        self.assertTrue(delta["content"].startswith(tag))

    def test_guard_anthropic_content(self) -> None:
        tag = build_tier_tag("system_2", "Converge")
        data: dict = {"content": [{"type": "text", "text": "结论如下"}]}
        self.assertTrue(guard_anthropic_content(data, tag))
        self.assertTrue(data["content"][0]["text"].startswith(tag))

        tool_only: dict = {"content": [{"type": "tool_use", "name": "x"}]}
        # P0-2 contract: pure tool_use turns carry no user-facing text — never inject a tag block.
        self.assertFalse(guard_anthropic_content(tool_only, tag))
        self.assertEqual(tool_only["content"][0]["type"], "tool_use")

    def test_gateway_injects_tag_into_non_stream_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            qm = QuotaManager(REPO_ROOT / "proxy_gateway" / "quota_policy.yaml", Path(tmp) / "q.db")
            now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)

            async def mock_handler(request: httpx.Request) -> httpx.Response:
                return httpx.Response(
                    200,
                    json={
                        "id": "ok",
                        "choices": [{"message": {"role": "assistant", "content": "答案是 42"}}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                    },
                )

            app = create_app(
                openai_upstream="https://mock.local/v1",
                transport=httpx.MockTransport(mock_handler),
                quota_manager=qm,
                now_provider=lambda: now,
            )
            client = TestClient(app)
            resp = client.post(
                "/v1/chat/completions",
                json={"stream": False, "messages": [{"role": "user", "content": "分析一下架构"}]},
            )
            self.assertEqual(resp.status_code, 200)
            content = resp.json()["choices"][0]["message"]["content"]
            self.assertTrue(content.startswith("[Tier: Structured Analysis (Tier 1.5)"), content)
            self.assertEqual(
                resp.headers["x-harness-tier-tag"],
                "[Tier: Structured Analysis (Tier 1.5) | Mode: Explore]",
            )

    def test_gateway_leaves_compliant_response_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            qm = QuotaManager(REPO_ROOT / "proxy_gateway" / "quota_policy.yaml", Path(tmp) / "q.db")
            now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
            compliant = "[Tier: Structured Analysis (Tier 1.5) | Mode: Converge]\n\n答案是 42"

            async def mock_handler(request: httpx.Request) -> httpx.Response:
                return httpx.Response(
                    200,
                    json={
                        "id": "ok",
                        "choices": [{"message": {"role": "assistant", "content": compliant}}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                    },
                )

            app = create_app(
                openai_upstream="https://mock.local/v1",
                transport=httpx.MockTransport(mock_handler),
                quota_manager=qm,
                now_provider=lambda: now,
            )
            client = TestClient(app)
            resp = client.post(
                "/v1/chat/completions",
                json={"stream": False, "messages": [{"role": "user", "content": "分析一下架构"}]},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["choices"][0]["message"]["content"], compliant)


if __name__ == "__main__":
    unittest.main()
