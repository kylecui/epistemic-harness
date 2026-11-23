"""Gateway interim-schema guard: mode parsing, header opt-in, validation, opt-in note."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from orchestrator.subagent_report import build_report  # noqa: E402
from proxy_gateway.app import create_app  # noqa: E402
from proxy_gateway.interim_guard import (  # noqa: E402
    check_interim_response,
    interim_mode,
    interim_note,
    requested_interim_schema,
)


class InterimGuardUnitTests(unittest.TestCase):
    def test_mode_defaults_to_off(self):
        saved = os.environ.pop("HARNESS_INTERIM_SCHEMA", None)
        try:
            self.assertEqual(interim_mode(), "off")
        finally:
            if saved is not None:
                os.environ["HARNESS_INTERIM_SCHEMA"] = saved

    def test_header_opt_in(self):
        self.assertEqual(requested_interim_schema("subagent-report/v1"), "subagent-report/v1")
        self.assertIsNone(requested_interim_schema("text"))
        self.assertIsNone(requested_interim_schema(None))

    def test_valid_report_passes_and_invalid_fails(self):
        ok = json.dumps(build_report("t-1", "coder", "finding"), ensure_ascii=False)
        self.assertEqual(check_interim_response(ok, "subagent-report/v1"), (True, []))
        good, violations = check_interim_response("not json", "subagent-report/v1")
        self.assertFalse(good)
        self.assertTrue(violations)
        self.assertIn("violations", interim_note("subagent-report/v1", violations))


class InterimGuardAppTests(unittest.TestCase):
    def _app(self, body: str):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "id": "x", "object": "chat.completion", "model": "m",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": body}, "finish_reason": "stop"}],
                "usage": {},
            })
        return create_app(openai_upstream="https://mock.openai.local/v1", transport=httpx.MockTransport(handler))

    def test_off_by_default_no_note(self):
        client = TestClient(self._app("free text"))
        resp = client.post("/v1/chat/completions", headers={"X-Harness-Interim": "subagent-report/v1"},
                           json={"model": "m", "messages": [{"role": "user", "content": "hi"}]})
        self.assertNotIn("HARNESS_INTERIM", resp.text)

    def test_warn_appends_note_on_violation(self):
        os.environ["HARNESS_INTERIM_SCHEMA"] = "warn"
        try:
            client = TestClient(self._app("free text, not a report"))
            resp = client.post("/v1/chat/completions", headers={"X-Harness-Interim": "subagent-report/v1"},
                               json={"model": "m", "messages": [{"role": "user", "content": "hi"}]})
            self.assertIn("HARNESS_INTERIM", resp.text)
            self.assertIn("not valid JSON", resp.text)
        finally:
            os.environ.pop("HARNESS_INTERIM_SCHEMA", None)

    def test_warn_silent_on_valid_report(self):
        os.environ["HARNESS_INTERIM_SCHEMA"] = "warn"
        try:
            valid = json.dumps(build_report("t-1", "coder", "finding"), ensure_ascii=False)
            client = TestClient(self._app(valid))
            resp = client.post("/v1/chat/completions", headers={"X-Harness-Interim": "subagent-report/v1"},
                               json={"model": "m", "messages": [{"role": "user", "content": "hi"}]})
            self.assertNotIn("HARNESS_INTERIM", resp.text)
        finally:
            os.environ.pop("HARNESS_INTERIM_SCHEMA", None)


if __name__ == "__main__":
    unittest.main()
