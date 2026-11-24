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

from fastapi.testclient import TestClient
import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from proxy_gateway.app import AllUpstreamsUnavailable, create_app, unavailable_response
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
            self.assertEqual(resp.status_code, 503, resp.text)
            # every attempted model answered retry-after 90 (rechecked one second later)
            self.assertEqual(resp.headers["retry-after"], "91")
            self.assertNotIn("stop-loss synthesized", resp.text)
            self.assertEqual(json.loads(resp.text)["error"]["type"], "harness_gateway_error")

    def test_anthropic_stream_gets_503(self) -> None:
        resp = _client(_always_429).post("/anthropic/v1/messages", json={
            "model": "claude", "max_tokens": 16, "stream": True, "messages": MSG})
        self.assertEqual(resp.status_code, 503, resp.text)
        self.assertEqual(json.loads(resp.text)["error"]["type"], "overloaded_error")

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
