"""Gemini thought_signature round trip (HTTP 400 "missing a thought_signature" after tool calls)."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import proxy_gateway.app as app_module
from proxy_gateway.app import create_app
from proxy_gateway.thought_signature_store import ThoughtSignatureStore

SIG = "sig-abc"
TOOL_CALL_CHUNK = {"id": "c1", "choices": [{"delta": {"tool_calls": [
    {"index": 0, "id": "call_1", "type": "function", "function": {"name": "read", "arguments": "{}"},
     "extra_content": {"google": {"thought_signature": SIG}}}]}}]}


class StoreTests(unittest.TestCase):
    def test_record_stream_chunk_and_attach_by_id(self) -> None:
        store = ThoughtSignatureStore()
        store.record_chunk(TOOL_CALL_CHUNK)
        body = {"messages": [{"role": "assistant", "tool_calls": [{"id": "call_1", "type": "function"}]}]}
        self.assertEqual(store.inject(body), 1)
        self.assertEqual(body["messages"][0]["tool_calls"][0]["extra_content"]["google"]["thought_signature"], SIG)

    def test_record_non_stream_message_shape(self) -> None:
        store = ThoughtSignatureStore()
        store.record_chunk({"choices": [{"message": TOOL_CALL_CHUNK["choices"][0]["delta"]}]})
        self.assertEqual(store._lookup("call_1"), SIG)

    def test_skips_entries_that_already_have_a_signature(self) -> None:
        store = ThoughtSignatureStore()
        store.record_chunk(TOOL_CALL_CHUNK)
        call = {"id": "call_1", "extra_content": {"google": {"thought_signature": "mine"}}}
        self.assertEqual(store.inject({"messages": [{"tool_calls": [call]}]}), 0)
        self.assertEqual(call["extra_content"]["google"]["thought_signature"], "mine")

    def test_unknown_id_is_left_alone(self) -> None:
        store = ThoughtSignatureStore()
        store.record_chunk(TOOL_CALL_CHUNK)
        call = {"id": "call_other"}
        self.assertEqual(store.inject({"messages": [{"tool_calls": [call]}]}), 0)
        self.assertNotIn("extra_content", call)

    def test_tolerates_malformed_messages_and_is_bounded(self) -> None:
        store = ThoughtSignatureStore(capacity=2)
        self.assertEqual(store.inject({"messages": [None, "x", {"tool_calls": [None, 3]}]}), 0)
        for i in range(5):
            store.record_chunk({"choices": [{"delta": {"tool_calls": [
                {"id": f"c{i}", "extra_content": {"google": {"thought_signature": f"s{i}"}}}]}}]})
        self.assertIsNone(store._lookup("c0"))
        self.assertEqual(store._lookup("c4"), "s4")


class WiringTests(unittest.TestCase):
    def test_signature_from_response_is_resent_on_next_request_to_google(self) -> None:
        captured: list[dict] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode("utf-8"))
            captured.append(body)
            sse = f'data: {json.dumps(TOOL_CALL_CHUNK)}\n\ndata: {{"id":"c1","choices":[{{"delta":{{}},"finish_reason":"tool_calls"}}]}}\n\ndata: [DONE]\n\n'
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse.encode("utf-8"))

        app = create_app(openai_upstream="https://mock.openai.local/v1", transport=httpx.MockTransport(handler))
        client = TestClient(app)
        with patch.object(app_module, "_resolve_base", return_value="https://generativelanguage.googleapis.com/v1beta/openai"):
            client.post("/v1/chat/completions", json={"model": "zhipu-glm-5.4", "stream": True,
                                                      "messages": [{"role": "user", "content": "hi"}]})
            follow_up = {"model": "zhipu-glm-5.4", "stream": True, "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "tool_calls": [{"id": "call_1", "type": "function",
                                                     "function": {"name": "read", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "call_1", "content": "ok"}]}
            client.post("/v1/chat/completions", json=follow_up)

        # The gateway prepends its own system message, so locate the assistant turn by role.
        assistant = next(m for m in captured[-1]["messages"] if m.get("role") == "assistant")
        sent = assistant["tool_calls"][0]
        self.assertEqual(sent["extra_content"]["google"]["thought_signature"], SIG)
        self.assertEqual(follow_up["messages"][1]["tool_calls"][0].get("extra_content"), None)  # caller untouched


if __name__ == "__main__":
    unittest.main()
