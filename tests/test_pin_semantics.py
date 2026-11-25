"""Issue #22: a pinned model is never replaced without the client's consent.

Three outcomes, each checked through the real handlers:

  unknown id        -> HTTP 404 unknown_model, naming ids the gateway does serve
  known, unservable -> HTTP 503 + Retry-After naming the reason; no substitute is served
  opted-in swap     -> HTTP 200 + X-Harness-Served-Model and a harness{} block in the body,
                       because pi reads the body and never the response headers
"""

from __future__ import annotations

from datetime import datetime, timezone
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
from proxy_gateway.app import create_app
from proxy_gateway.quota_manager import QuotaManager

POLICY = REPO_ROOT / "proxy_gateway" / "quota_policy.yaml"
NOW = datetime(2026, 11, 25, 16, 0, tzinfo=timezone.utc)  # off-peak for the zhipu pilot
TIER = "system_1_5"
PIN = "zhipu-glm-5.4"  # first candidate of the system_1_5 chain
AN_PIN = "zhipu-glm-5.4-anthropic"  # same pool, anthropic protocol
UNKNOWN = "lab-nonexistent-pin"
MSG = [{"role": "user", "content": "hi"}]
ALLOW = {"X-Harness-Allow-Substitute": "1"}


def _upstream(request: httpx.Request) -> httpx.Response:
    """Answers any candidate: the pin tests care which model was asked, not what it says."""
    body = json.loads(request.content.decode("utf-8") or "{}")
    if request.url.path.endswith("/v1/messages"):
        if body.get("stream"):
            sse = (
                'event: content_block_delta\n'
                'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"ok"}}\n\n'
                'event: message_stop\ndata: {"type":"message_stop"}\n\n'
            )
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse.encode("utf-8"))
        return httpx.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": body.get("model", ""),
            "content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1}})
    if body.get("stream"):
        sse = (
            'data: {"id":"c1","choices":[{"delta":{"content":"ok"},"finish_reason":null}]}\n\n'
            'data: {"id":"c1","choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse.encode("utf-8"))
    return httpx.Response(200, json={"id": "c1", "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                                     "usage": {}})


class PinTestBase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.qm = QuotaManager(POLICY, self.tmp / "q.db", holds_path=self.tmp / "holds.json")
        self.client = TestClient(self._app())

    def _app(self):
        return create_app(
            openai_upstream="https://mock.openai.local/v1",
            anthropic_upstream="https://mock.anthropic.local",
            transport=httpx.MockTransport(_upstream),
            quota_manager=self.qm,
            now_provider=lambda: NOW,
        )

    def lock_the_pin(self) -> None:
        self.qm.hold(PIN, 240, "weekly cap spent", now_utc=NOW)
        self.qm.hold(AN_PIN, 240, "weekly cap spent", now_utc=NOW)


class UnknownPinTests(PinTestBase):
    def test_an_unknown_pin_is_a_404_that_names_what_we_serve(self) -> None:
        resp = self.client.post("/v1/chat/completions", headers={"X-Harness-Tier": TIER},
                                json={"model": UNKNOWN, "stream": False, "messages": MSG})
        self.assertEqual(resp.status_code, 404, resp.text)
        err = resp.json()["error"]
        self.assertEqual(err["type"], "unknown_model")
        self.assertIn(UNKNOWN, err["message"])
        self.assertTrue(err["available_models"], err)
        self.assertLessEqual(len(err["available_models"]), 5)
        self.assertIn("Available model ids", err["message"])
        self.assertNotIn("choices", resp.json())

    def test_the_anthropic_route_reports_the_same_404_in_its_own_shape(self) -> None:
        resp = self.client.post("/anthropic/v1/messages", headers={"X-Harness-Tier": TIER},
                                json={"model": UNKNOWN, "max_tokens": 16, "stream": False, "messages": MSG})
        self.assertEqual(resp.status_code, 404, resp.text)
        body = resp.json()
        self.assertEqual(body["type"], "error")
        self.assertEqual(body["error"]["type"], "unknown_model")
        self.assertIn(UNKNOWN, body["error"]["message"])

    def test_an_unknown_pin_never_reaches_an_upstream_and_leaves_one_event(self) -> None:
        trace = self.tmp / "traces.jsonl"
        with patch.object(app_module, "TRACE_FILE", trace):
            resp = self.client.post("/v1/chat/completions", headers={"X-Harness-Tier": TIER},
                                    json={"model": "zhipu-glm-5.44", "stream": False, "messages": MSG})
        self.assertEqual(resp.status_code, 404, resp.text)
        self.assertIn("zhipu-glm-5.4", resp.json()["error"]["near_matches"])
        events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual([e["event"] for e in events], ["unknown_model"])

    def test_the_escape_hatch_routes_a_foreign_label_instead_of_failing(self) -> None:
        """Claude Code labels its turns `claude-sonnet-4-5-...`; that is a label, not a pin."""
        with patch.dict("os.environ", {"HARNESS_FAIL_ON_UNKNOWN_MODEL": "off"}):
            client = TestClient(self._app())
            resp = client.post("/v1/chat/completions", headers={"X-Harness-Tier": TIER},
                               json={"model": "claude-sonnet-4-5-20250929", "stream": False, "messages": MSG})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn("choices", resp.json())


class RefusedPinTests(PinTestBase):
    def test_a_locked_pin_fails_with_its_reason_instead_of_being_replaced(self) -> None:
        self.lock_the_pin()
        resp = self.client.post("/v1/chat/completions", headers={"X-Harness-Tier": TIER},
                                json={"model": PIN, "stream": False, "messages": MSG})
        self.assertEqual(resp.status_code, 503, resp.text)
        self.assertEqual(resp.headers["x-harness-all-upstreams-unavailable"], "1")
        # The wait is the hold's own expiry, not the cooldown default: 240m, so >= 1h.
        self.assertGreaterEqual(int(resp.headers["retry-after"]), 3600)
        body = resp.json()
        message = body["error"]["message"]
        self.assertIn(PIN, message)
        self.assertIn("manual_hold", message)
        self.assertIn("X-Harness-Allow-Substitute", message)  # says how to opt in
        self.assertNotIn("choices", body)  # nothing was generated for a pin we could not honour

    def test_the_streaming_route_refuses_before_a_single_frame_is_sent(self) -> None:
        self.lock_the_pin()
        resp = self.client.post("/v1/chat/completions", headers={"X-Harness-Tier": TIER},
                                json={"model": PIN, "stream": True, "messages": MSG})
        self.assertEqual(resp.status_code, 503, resp.text)
        self.assertNotIn("data:", resp.text)

    def test_the_anthropic_route_refuses_too(self) -> None:
        self.lock_the_pin()
        resp = self.client.post("/anthropic/v1/messages", headers={"X-Harness-Tier": TIER},
                                json={"model": AN_PIN, "max_tokens": 16, "stream": False, "messages": MSG})
        self.assertEqual(resp.status_code, 503, resp.text)
        self.assertIn("manual_hold", resp.json()["error"]["message"])


class OptedInTests(PinTestBase):
    def test_the_opt_in_swaps_and_says_so_in_both_places(self) -> None:
        self.lock_the_pin()
        resp = self.client.post("/v1/chat/completions", headers={"X-Harness-Tier": TIER, **ALLOW},
                                json={"model": PIN, "stream": False, "messages": MSG})
        self.assertEqual(resp.status_code, 200, resp.text)
        served = resp.headers["x-harness-served-model"]
        self.assertNotEqual(served, PIN)
        self.assertEqual(served, resp.headers["x-harness-selected-model"])
        harness = resp.json()["harness"]
        self.assertEqual(harness["requested_model"], PIN)
        self.assertEqual(harness["served_model"], served)
        self.assertTrue(harness["substituted"])
        self.assertIn("manual_hold", harness["reason"])
        self.assertLessEqual(len(harness["skipped_reasons"].split(";")), 5)
        self.assertIn("x-harness-skip-reasons", resp.headers)

    def test_the_streaming_route_announces_the_swap_in_the_headers(self) -> None:
        self.lock_the_pin()
        resp = self.client.post("/v1/chat/completions", headers={"X-Harness-Tier": TIER, **ALLOW},
                                json={"model": PIN, "stream": True, "messages": MSG})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertNotEqual(resp.headers["x-harness-served-model"], PIN)
        self.assertIn("data:", resp.text)

    def test_the_anthropic_route_announces_it_in_the_body_too(self) -> None:
        self.lock_the_pin()
        resp = self.client.post("/anthropic/v1/messages", headers={"X-Harness-Tier": TIER, **ALLOW},
                                json={"model": AN_PIN, "max_tokens": 16, "stream": False, "messages": MSG})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertNotEqual(resp.headers["x-harness-served-model"], AN_PIN)
        self.assertTrue(resp.json()["harness"]["substituted"])
        self.assertEqual(resp.json()["harness"]["requested_model"], AN_PIN)


class PinIdentityTests(PinTestBase):
    """A pin may arrive as a provider id; it must land on the catalog key the chain uses."""

    def test_an_upstream_id_names_the_same_pin_as_its_catalog_key(self) -> None:
        resp = self.client.post("/v1/chat/completions", headers={"X-Harness-Tier": TIER},
                                json={"model": "k3.1-pro", "stream": False, "messages": MSG})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.headers["x-harness-selected-model"], "kimi-k3.1-pro")
        self.assertNotIn("x-harness-served-model", resp.headers)  # the pin was honoured, not dropped

    def test_an_ambiguous_upstream_id_follows_the_route_protocol(self) -> None:
        resp = self.client.post("/anthropic/v1/messages", headers={"X-Harness-Tier": TIER},
                                json={"model": "k3.1-pro", "max_tokens": 16, "stream": False, "messages": MSG})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.headers["x-harness-selected-model"], "kimi-k3.1-pro-anthropic")

    def test_a_pin_outside_the_tier_chain_is_refused_with_that_reason(self) -> None:
        resp = self.client.post("/v1/chat/completions", headers={"X-Harness-Tier": "system_0"},
                                json={"model": "kimi-k3.1-pro", "stream": False, "messages": MSG})
        self.assertEqual(resp.status_code, 503, resp.text)
        self.assertIn("not_in_tier_chain(system_0)", resp.json()["error"]["message"])


class HonouredPinTests(PinTestBase):
    def test_the_pin_answers_and_nothing_extra_is_added(self) -> None:
        resp = self.client.post("/v1/chat/completions", headers={"X-Harness-Tier": TIER},
                                json={"model": PIN, "stream": False, "messages": MSG})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.headers["x-harness-selected-model"], PIN)
        self.assertNotIn("x-harness-served-model", resp.headers)  # no substitution, no warning
        self.assertNotIn("x-harness-skip-reasons", resp.headers)
        self.assertNotIn("harness", resp.json())

    def test_a_request_that_names_no_model_gains_no_pin_signal(self) -> None:
        resp = self.client.post("/v1/chat/completions", headers={"X-Harness-Tier": TIER},
                                json={"stream": False, "messages": MSG})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertNotIn("x-harness-served-model", resp.headers)
        self.assertNotIn("harness", resp.json())


class TraceTests(PinTestBase):
    def test_both_paths_trace_the_pin_the_served_model_and_the_skip_map(self) -> None:
        trace = self.tmp / "traces.jsonl"
        self.lock_the_pin()
        with patch.object(app_module, "TRACE_FILE", trace):
            for stream in (False, True):
                self.client.post("/v1/chat/completions", headers={"X-Harness-Tier": TIER, **ALLOW},
                                 json={"model": PIN, "stream": stream, "messages": MSG})
        rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines() if line.strip()]
        rows = [r for r in rows if r.get("selected_model")]
        self.assertEqual(len(rows), 2, rows)  # one per path, streaming included
        for row in rows:
            self.assertEqual(row["requested_model"], PIN)
            self.assertNotEqual(row["selected_model"], PIN)
            self.assertTrue(row["pin_dropped"])
            self.assertIn(PIN, row["skipped_reasons"])

    def test_a_refusal_leaves_its_own_event(self) -> None:
        trace = self.tmp / "traces.jsonl"
        self.lock_the_pin()
        with patch.object(app_module, "TRACE_FILE", trace):
            self.client.post("/v1/chat/completions", headers={"X-Harness-Tier": TIER},
                             json={"model": PIN, "stream": False, "messages": MSG})
        events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines() if line.strip()]
        refused = [e for e in events if e.get("event") == "pin_refused"]
        self.assertEqual(len(refused), 1, events)
        self.assertEqual(refused[0]["requested_model"], PIN)
        self.assertIn("manual_hold", refused[0]["pin_dropped"])


if __name__ == "__main__":
    unittest.main()
