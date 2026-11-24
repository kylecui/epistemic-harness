import json
from pathlib import Path
import sys
import unittest

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from proxy_gateway.response_guard import (
    StreamTagGuard,
    guard_anthropic_content,
    guard_openai_message,
    detect_mode,
)
from proxy_gateway.exclude_policy import resolve_excluded_pool
from orchestrator.dispatch import dispatch_subtask
from orchestrator.plan import run_plan


class TestRemediationFixes(unittest.TestCase):
    # --- P0-2: response_guard fixes ---
    def test_p0_2_skips_pure_tool_use_and_tool_calls(self) -> None:
        an_resp = {"content": [{"type": "tool_use", "id": "t1", "name": "query_l1", "input": {}}]}
        self.assertFalse(guard_anthropic_content(an_resp, "[Tier: Structured Analysis | Mode: Explore]"))
        self.assertEqual(len(an_resp["content"]), 1)

        oa_resp = {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}]}}]}
        self.assertFalse(guard_openai_message(oa_resp, "[Tier: Structured Analysis | Mode: Explore]"))

    def test_p0_2_stream_tag_guard_prevents_duplicate_tag_on_split_chunks(self) -> None:
        tag = "[Tier: Structured Analysis (Tier 1.5) | Mode: Explore]"
        guard = StreamTagGuard(tag)
        # Upstream splits `[Tier: ...]` across 3 tiny chunks
        self.assertIsNone(guard.feed("["))
        self.assertIsNone(guard.feed("Tier: Structured"))
        out = guard.feed(" Analysis] Hello world")
        self.assertEqual(out, "[Tier: Structured Analysis] Hello world")
        self.assertFalse(guard.injected)

        # Upstream omits tag completely -> injects exactly once
        guard2 = StreamTagGuard(tag)
        out2 = guard2.feed("Direct answer without tag")
        self.assertTrue(guard2.injected)
        self.assertTrue(out2.startswith(tag))

    def test_p0_2_system_1_5_defaults_to_explore_not_converge(self) -> None:
        self.assertEqual(detect_mode("帮我分析一下这个报错可能的原因", "system_1_5"), "Explore")
        self.assertEqual(detect_mode("进入收敛态，给我最终拍板", "system_1_5"), "Converge")

    # --- P0-1 & P0-3: dispatch SSE streaming + cross-family critic header ---
    def test_p0_1_and_p0_3_sse_dispatch_and_cross_family_header(self) -> None:
        seen_headers: list[dict[str, str]] = []
        seen_streams: list[bool] = []

        def mock_handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode("utf-8"))
            seen_streams.append(bool(body.get("stream")))
            seen_headers.append({k.lower(): v for k, v in request.headers.items()})
            sse = (
                'data: {"choices":[{"delta":{"content":"[Tier: Fast Intuition | Mode: Explore] "}}]}\n\n'
                'data: {"choices":[{"delta":{"content":"Using L3-ARCH-001 heuristic."}}]}\n\n'
                'data: [DONE]\n\n'
            )
            return httpx.Response(
                200,
                headers={
                    "content-type": "text/event-stream",
                    "X-Harness-Selected-Model": "kimi-k3.1-pro",
                    "X-Harness-Routed-Tier": "system_1_5",
                },
                content=sse.encode("utf-8"),
            )

        res = dispatch_subtask(
            agent_profile="analyst",
            task_text="Evaluate microservices",
            task_id="S1",
            transport=httpx.MockTransport(mock_handler),
            exclude_model="zhipu-glm-5.4",
        )
        self.assertEqual(seen_streams, [True])  # P0-3: SSE streaming enabled!
        self.assertEqual(seen_headers[0]["x-harness-exclude-model"], "zhipu-glm-5.4")  # P0-1!
        self.assertIn("L3-ARCH-001", res["content"])

        # Verify gateway helper maps excluded model -> its shared pool
        class _DummyQM:
            models = {"zhipu-glm-5.4": {"pool": "zhipu_v2_max"}}
            def pool_for_model(self, mk):
                return ("zhipu_v2_max", {})

        ex_pool = resolve_excluded_pool(seen_headers[0], _DummyQM(), {}, "S1", is_critic=True)
        self.assertEqual(ex_pool, "zhipu_v2_max")

    # --- P0-4 & P1-1: resilient wave isolation + English synthesis + EpistemicEngine DAG bridge ---
    def test_p0_4_and_p1_1_partial_failure_isolation_and_dag_audit(self) -> None:
        # Import real EpistemicEngine from our Phase 1 repo if available
        phase1_root = Path(__file__).resolve().parent.parent.parent / "epistemic-harness-phase1"
        engine = None
        if phase1_root.exists():
            sys.path.insert(0, str(phase1_root))
            from mcp_server.dag_engine import EpistemicEngine
            engine = EpistemicEngine(phase1_root)

        captured_prompts: list[str] = []

        def mock_handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode("utf-8"))
            user_msg = body["messages"][-1]["content"]
            captured_prompts.append(user_msg)
            if "FAIL_ME" in user_msg:
                return httpx.Response(500, json={"error": "simulated upstream timeout"})
            sse = (
                'data: {"choices":[{"delta":{"content":"Based on L3-ARCH-001 and L1-REL-001, prefer modular monolith."}}]}\n\n'
                'data: [DONE]\n\n'
            )
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream", "X-Harness-Selected-Model": "zhipu-glm-5.4"},
                content=sse.encode("utf-8"),
            )

        out = run_plan(
            subtasks=[
                {"id": "S1", "task_text": "Analyze architecture with L3-ARCH-001"},
                {"id": "S2", "task_text": "FAIL_ME simulated subtask failure"},
            ],
            original_task="Design startup SaaS architecture",
            synthesize=True,
            transport=httpx.MockTransport(mock_handler),
            epistemic_engine=engine,
        )
        # S1 survived even though sibling S2 failed in the same parallel wave!
        self.assertEqual(out["results"]["S1"]["status"], "ok")
        self.assertEqual(out["results"]["S2"]["status"], "error")
        # Synthesis prompt is in English (no Chinese hardcoding!)
        synth_prompt = captured_prompts[-1]
        self.assertIn("Synthesize the following subtask outputs", synth_prompt)
        self.assertIn("Respond strictly in the same language", synth_prompt)
        # EpistemicEngine DAG audit ran and capped confidence at L3 due to L3-ARCH-001!
        if engine is not None:
            self.assertIsNotNone(out["dag_audit"])
            self.assertEqual(out["dag_audit"]["overall_confidence_cap"], "L3")


if __name__ == "__main__":
    unittest.main()
