"""X-Harness-No-Contract must give a machine consumer the model's own text (no Tier tag)."""
from __future__ import annotations

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


def _openai_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"id": "x", "object": "chat.completion", "created": 1, "model": "m",
                                     "choices": [{"index": 0, "finish_reason": "stop",
                                                  "message": {"role": "assistant", "content": "PLAIN"}}]})


def _reply(headers: dict) -> str:
    app = create_app(openai_upstream="https://mock.openai.local/v1",
                     anthropic_upstream="https://mock.anthropic.local",
                     transport=httpx.MockTransport(_openai_ok))
    with TestClient(app) as client:
        resp = client.post("/v1/chat/completions", headers=headers,
                           json={"model": "zhipu-glm-5.4", "stream": False, "messages": MSG})
    return resp.json()["choices"][0]["message"]["content"]


class NoContractTests(unittest.TestCase):
    def test_a_machine_consumer_gets_no_tier_tag(self) -> None:
        text = _reply({"X-Harness-No-Contract": "1"})
        self.assertEqual(text, "PLAIN", f"tag leaked into a machine-facing reply: {text[:60]!r}")

    def test_a_normal_turn_still_gets_the_tag(self) -> None:
        self.assertTrue(_reply({}).startswith("[Tier:"))


if __name__ == "__main__":
    unittest.main()
