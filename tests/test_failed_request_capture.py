"""Failed-request capture (issue #18): the exact upstream payload is kept on HTTP 400."""

from __future__ import annotations

import json
from datetime import datetime
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
from proxy_gateway.app import capture_failed_request, create_app


class CaptureTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self._patch = patch.object(app_module, "FAILED_REQUEST_DIR", self.dir)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    def test_400_keeps_payload_and_upstream_body(self) -> None:
        name = capture_failed_request("m", 400, {"messages": [{"role": "user", "content": "hi"}]}, "bad field")
        saved = json.loads((self.dir / name).read_text(encoding="utf-8"))
        self.assertEqual(saved["request"]["messages"][0]["content"], "hi")
        self.assertEqual(saved["status"], 400)
        self.assertEqual(saved["upstream_body"], "bad field")

    def test_other_statuses_and_malformed_payload_capture_nothing(self) -> None:
        for status, payload in ((429, {"a": 1}), (401, {"a": 1}), (500, {"a": 1}), (400, [1, 2]), (400, None)):
            self.assertIsNone(capture_failed_request("m", status, payload, ""))
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_keeps_only_the_newest_thirty(self) -> None:
        for _ in range(35):
            capture_failed_request("m", 400, {"a": 1}, "")
        self.assertEqual(len(list(self.dir.glob("*.json"))), app_module._FAILED_REQUEST_KEEP)

    def test_two_captures_in_the_same_microsecond_are_both_kept(self) -> None:
        real = datetime

        class Frozen:
            @staticmethod
            def now(tz=None):
                return real(2026, 11, 24, 12, 0, 0, 123456, tzinfo=tz)

        with patch.object(app_module, "datetime", Frozen):
            first = capture_failed_request("m", 400, {"n": 1}, "")
            second = capture_failed_request("m", 400, {"n": 2}, "")
        self.assertNotEqual(first, second)
        saved = [json.loads((self.dir / name).read_text(encoding="utf-8"))["request"]["n"]
                 for name in (first, second)]
        self.assertEqual(sorted(saved), [1, 2])  # neither overwrote the other

    def test_a_400_on_the_stream_route_is_written_with_the_sent_body(self) -> None:
        calls: list[dict] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            calls.append(json.loads(request.content.decode("utf-8")))
            if len(calls) == 1:
                return httpx.Response(400, json={"error": {"message": "missing a thought_signature"}})
            sse = 'data: {"id":"1","choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse.encode("utf-8"))

        app = create_app(openai_upstream="https://mock.openai.local/v1", transport=httpx.MockTransport(handler))
        TestClient(app).post("/v1/chat/completions", json={
            "model": "zhipu-glm-5.4", "stream": True,
            "messages": [{"role": "user", "content": "capture me"}]})
        files = list(self.dir.glob("*-400.json"))
        self.assertEqual(len(files), 1)
        self.assertEqual(json.loads(files[0].read_text(encoding="utf-8"))["request"], calls[0])


if __name__ == "__main__":
    unittest.main()
