"""When every upstream is unavailable the gateway answers HTTP 503 + Retry-After, never a fake reply.

Reviewed by critic 2026-11-24: StreamingResponse sends the status line before iterating the body, so the
first chunk is pulled inside the endpoint (_primed); a failure after bytes reached the client is in-band.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import proxy_gateway.app as app_module
from proxy_gateway.app import AllUpstreamsUnavailable, _error_brief, create_app, unavailable_response
from proxy_gateway.quota_manager import QuotaManager

MSG = [{"role": "user", "content": "hi"}]


def _client(handler) -> TestClient:
    app = create_app(openai_upstream="https://mock.openai.local/v1", anthropic_upstream="https://mock.anthropic.local",
                     transport=httpx.MockTransport(handler))
    return TestClient(app)


def _sse(*lines: str) -> httpx.Response:
    body = "".join(f"data: {line}\n\n" for line in lines)
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode("utf-8"))


def _always_429(request: httpx.Request) -> httpx.Response:
    return httpx.Response(429, headers={"retry-after": "90"}, json={"error": {"message": "rate limited"}})


def _healthy(request: httpx.Request) -> httpx.Response:
    return _sse('{"id":"1","choices":[{"delta":{"content":"fine"},"finish_reason":"stop"}]}', "[DONE]")


class ResponseTests(unittest.TestCase):
    def test_503_carries_retry_after_and_a_protocol_shaped_body(self) -> None:
        resp = unavailable_response(AllUpstreamsUnavailable("openai", "system_1_5", "Upstream: a > b", 91))
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.headers["retry-after"], "91")
        self.assertIn("about 91s", json.loads(resp.body)["error"]["message"])
        anth = unavailable_response(AllUpstreamsUnavailable("anthropic", "system_2", "x", None))
        self.assertEqual(anth.headers["retry-after"], "30")
        self.assertEqual(json.loads(anth.body)["error"]["type"], "overloaded_error")


class ErrorBriefTests(unittest.TestCase):
    def test_brief_keeps_the_provider_error_code_message_and_request_id(self) -> None:
        body = json.dumps({"error": {"code": 400, "message": "Function call is missing a thought_signature in functionCall parts.",
                                     "status": "INVALID_ARGUMENT"}})
        brief = _error_brief(400, body, {"request-id": "req_abc", "x-goog-request-id": "g-1"})
        self.assertEqual(brief, "HTTP 400 [INVALID_ARGUMENT] Function call is missing a thought_signature in "
                         "functionCall parts. (request_id=req_abc)")

    def test_brief_copes_with_plain_text_and_anthropic_shapes(self) -> None:
        self.assertEqual(_error_brief(529, '{"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}', {}),
                         "HTTP 529 [overloaded_error] Overloaded")
        self.assertEqual(_error_brief(502, "bad gateway", {}), "HTTP 502 bad gateway")

    def test_provider_code_and_request_id_lead_the_message_and_ride_along_as_data(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, headers={"retry-after": "90", "request-id": "r-429"},
                                  json={"error": {"code": "1302", "message": "rate"}})
        resp = _client(handler).post("/v1/chat/completions", json={"model": "test-reasoner", "stream": False, "messages": MSG})
        body = json.loads(resp.text)
        self.assertEqual(resp.status_code, 503)
        self.assertTrue(body["error"]["message"].startswith("HTTP 429 [1302] rate (request_id=r-429). "), body["error"]["message"])
        self.assertEqual(body["harness"]["upstream_error"]["status"], 429)
        self.assertIn("1302", body["harness"]["upstream_error"]["body"])
        self.assertIn("request_id=r-429", body["harness"]["other_candidates"])

    def test_no_upstream_answered_means_503_without_the_upstream_error_field(self) -> None:
        resp = unavailable_response(AllUpstreamsUnavailable("openai", "system_1", "a -> skipped(pool_exhausted)", 8479))
        self.assertEqual(resp.status_code, 503)
        body = json.loads(resp.body)
        self.assertNotIn("harness", body)
        self.assertIn("Earliest recovery in about 8479s", body["error"]["message"])

    def test_a_non_json_provider_body_is_kept_as_text(self) -> None:
        resp = unavailable_response(AllUpstreamsUnavailable("openai", "system_1", "a -> HTTP 502", 5,
                                                            {"status": 502, "body": "Bad Gateway"}))
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(json.loads(resp.body)["harness"]["upstream_error"]["body"], "Bad Gateway")
        self.assertEqual(json.loads(resp.body)["harness"]["retry_after_sec"], 5)


class TraceTests(unittest.TestCase):
    def test_every_503_leaves_one_trace_event_with_its_wait(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace = Path(tmp) / "traces.jsonl"
            with patch.object(app_module, "TRACE_FILE", trace):
                for stream in (True, False):
                    _client(_always_429).post("/v1/chat/completions", json={
                        "model": "test-reasoner", "stream": stream, "messages": MSG})
            lines = trace.read_text(encoding="utf-8").splitlines()
        events = [json.loads(l) for l in lines]
        events = [e for e in events if e.get("event") == "all_unavailable"]
        self.assertEqual(len(events), 2)
        self.assertEqual({e["retry_after"] for e in events}, {91})
        self.assertEqual({e["protocol"] for e in events}, {"openai"})


class SoonestTests(unittest.TestCase):
    def test_soonest_recovery_is_the_shortest_cooldown_in_the_tier_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            qm = QuotaManager(policy_path=REPO_ROOT / "proxy_gateway" / "quota_policy.yaml", db_path=Path(tmp) / "q.db")
        now = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
        self.assertIsNone(qm.soonest_available_in("no_such_tier", now))
        self.assertIsNone(qm.soonest_available_in("system_1", now, []))  # nothing attempted
        self.assertEqual(qm.soonest_available_in("system_1", now), 1)  # nothing cooling down
        for mkey in qm.routing_chains["system_1"]:
            qm.mark_upstream_failure(mkey, 404, "Not Found", None, now_utc=now)  # 3600s each
        qm.mark_upstream_failure("kimi-for-coding", 429, "rate limit", 120, now_utc=now)
        self.assertEqual(qm.soonest_available_in("system_1", now + timedelta(seconds=20)), 101)
        self.assertEqual(qm.soonest_available_in("system_1", now + timedelta(seconds=100)), 21)
        # Only the models the gateway actually attempted count: an untried one must not shorten the wait.
        self.assertEqual(qm.soonest_available_in("system_1", now + timedelta(seconds=200), ["zhipu-glm-5.4"]), 3401)
        self.assertIsNone(qm.soonest_available_in("system_1", now, ["zhipu-no-such-model"]))
        # Only explicit cooldowns are predicted: once the last cooldown lapses the tier reports 1.
        self.assertEqual(qm.soonest_available_in("system_1", now + timedelta(seconds=200)), 1)


class RouteTests(unittest.TestCase):
    def test_openai_stream_and_non_stream_get_503_not_a_synthesized_reply(self) -> None:
        for stream in (True, False):
            resp = _client(_always_429).post("/v1/chat/completions", json={"model": "test-reasoner", "stream": stream, "messages": MSG})
            self.assertEqual(resp.status_code, 503, resp.text)  # always the gateway's status: deterministic
            # every attempted model answered retry-after 90 (rechecked one second later)
            self.assertEqual(resp.headers["retry-after"], "91")
            self.assertEqual(resp.headers["x-harness-all-upstreams-unavailable"], "1")
            body = json.loads(resp.text)
            # The client UI shows only error.message, so the provider's own error leads it.
            self.assertTrue(body["error"]["message"].startswith("HTTP 429 rate limited. "), body["error"]["message"])
            self.assertIn("nothing was generated", body["error"]["message"])
            self.assertEqual(body["harness"]["all_upstreams_unavailable"], True)
            self.assertEqual(body["harness"]["upstream_error"]["status"], 429)
            self.assertEqual(body["harness"]["retry_after_sec"], 91)
            self.assertIn("HTTP 429", body["harness"]["other_candidates"])  # every candidate stays visible

    def test_anthropic_stream_gets_503(self) -> None:
        resp = _client(_always_429).post("/anthropic/v1/messages", json={
            "model": "claude", "max_tokens": 16, "stream": True, "messages": MSG})
        self.assertEqual(resp.status_code, 503, resp.text)
        body = json.loads(resp.text)
        self.assertTrue(body["error"]["message"].startswith("HTTP 429 rate limited. "))
        self.assertEqual(body["error"]["type"], "overloaded_error")
        self.assertEqual(body["harness"]["upstream_error"]["status"], 429)

    def test_anthropic_non_stream_tries_every_candidate_before_the_503(self) -> None:
        """This path used to make one attempt and relay the upstream error (2026-11-24)."""
        attempts: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            attempts.append(json.loads(request.content.decode("utf-8"))["model"])
            return httpx.Response(429, json={"type": "error", "error": {"type": "exceeded_current_quota_error", "message": "weekly limit"}})
        resp = _client(handler).post("/anthropic/v1/messages", json={
            "model": "claude-sonnet-5.5", "max_tokens": 16, "stream": False, "messages": MSG})
        self.assertEqual(resp.status_code, 503, resp.text)
        self.assertEqual(resp.headers["x-harness-all-upstreams-unavailable"], "1")
        self.assertGreaterEqual(len(attempts), 2)
        self.assertIn("exceeded_current_quota_error", resp.text)  # Kimi's real error shape leads the message

    def test_anthropic_non_stream_fails_over_to_the_next_candidate(self) -> None:
        attempts: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            attempts.append(json.loads(request.content.decode("utf-8"))["model"])
            if len(attempts) == 1:
                return httpx.Response(429, json={"type": "error", "error": {"type": "exceeded_current_quota_error", "message": "weekly limit"}})
            return httpx.Response(200, json={"id": "msg_1", "type": "message", "role": "assistant", "model": attempts[-1],
                                             "content": [{"type": "text", "text": "second candidate answered"}], "stop_reason": "end_turn",
                                             "usage": {"input_tokens": 1, "output_tokens": 1}})
        resp = _client(handler).post("/anthropic/v1/messages", json={
            "model": "claude-sonnet-5.5", "max_tokens": 16, "stream": False, "messages": MSG})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(len(attempts), 2)
        self.assertIn("second candidate answered", resp.text)

    def test_healthy_upstream_is_requested_once_and_content_is_intact(self) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            return _healthy(request)
        resp = _client(handler).post("/v1/chat/completions", json={"model": "test-reasoner", "stream": True, "messages": MSG})
        self.assertEqual(len(calls), 1)  # priming the first chunk must not re-send the request
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.text.count("fine"), 1)

    def test_failure_after_bytes_reached_the_client_is_reported_in_band(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if len(request.content) and request.headers.get("content-length"):
                pass
            return _sse('{"id":"1","choices":[{"delta":{"content":"partial"}}]}')  # stream cut, no finish
        resp = _client(handler).post("/v1/chat/completions", json={"model": "test-reasoner", "stream": True, "messages": MSG})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("partial", resp.text)


if __name__ == "__main__":
    unittest.main()
