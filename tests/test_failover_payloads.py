"""#12: failover must survive odd upstream bodies instead of crashing or mis-shaping them."""
from __future__ import annotations

import json
import pathlib
import sys
import unittest

import httpx
from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from proxy_gateway.app import create_app  # noqa: E402

MSG = [{"role": "user", "content": "hi"}]


def _post(handler, model: str = "zhipu-glm-5.4") -> httpx.Response:
    app = create_app(openai_upstream="https://mock.openai.local/v1",
                     anthropic_upstream="https://mock.anthropic.local",
                     transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        return client.post("/v1/chat/completions",
                           json={"model": model, "stream": False, "messages": MSG})


class OddPayloadTests(unittest.TestCase):
    def test_a_list_shaped_error_body_is_wrapped_not_forwarded(self) -> None:
        resp = _post(lambda request: httpx.Response(400, json=[{"code": "bad", "message": "nope"}]))
        body = resp.json()
        self.assertIsInstance(body, dict, "a bare list breaks every client that expects an envelope")
        self.assertIn("error", body)

    def test_the_error_text_is_not_a_python_repr(self) -> None:
        resp = _post(lambda request: httpx.Response(500, json={"error": ["upstream", "boom"]}))
        text = json.dumps(resp.json(), ensure_ascii=False)
        self.assertNotIn("TypeError", text)
        self.assertNotIn("unhashable", text)


if __name__ == "__main__":
    unittest.main()
