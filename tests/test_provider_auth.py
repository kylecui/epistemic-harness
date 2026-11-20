"""Provider identity adapters: Copilot token exchange + fingerprint headers, Google headers."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest

from fastapi.testclient import TestClient
import httpx


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from proxy_gateway import provider_auth
from proxy_gateway.app import create_app
from proxy_gateway.provider_auth import CopilotAuth, copilot_dynamic_headers, google_headers
from proxy_gateway.quota_manager import QuotaManager

FUTURE = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
TOKEN = f"tid=abc;exp={FUTURE};proxy-ep=proxy.individual.githubcopilot.com;sku=monthly"


class TestCopilotAuth(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.auth = CopilotAuth()

    def test_exchange_derives_api_base_url_from_proxy_ep(self) -> None:
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["ua"] = request.headers.get("user-agent")
            seen["integration"] = request.headers.get("copilot-integration-id")
            return httpx.Response(200, json={"token": TOKEN, "expires_at": FUTURE})

        auth = CopilotAuth(transport=httpx.MockTransport(handler))
        import os
        os.environ["HARNESS_COPILOT_GITHUB_TOKEN"] = "gho_test"
        try:
            tok = auth.token()
        finally:
            del os.environ["HARNESS_COPILOT_GITHUB_TOKEN"]
        self.assertIsNotNone(tok)
        self.assertEqual(tok.base_url, "https://api.individual.githubcopilot.com")
        self.assertTrue(seen["url"].endswith("/copilot_internal/v2/token"))
        self.assertEqual(seen["ua"], "GitHubCopilotChat/0.35.0")
        self.assertEqual(seen["integration"], "vscode-chat")

    def test_dynamic_headers_follow_last_message_role(self) -> None:
        self.assertEqual(copilot_dynamic_headers({"messages": [{"role": "user", "content": "hi"}]})["X-Initiator"], "user")
        self.assertEqual(
            copilot_dynamic_headers({"messages": [{"role": "user", "content": "hi"},
                                                 {"role": "assistant", "content": "yo"}]})["X-Initiator"], "agent")
        self.assertEqual(
            copilot_dynamic_headers({"messages": [{"role": "user", "content": "hi"}]})["Openai-Intent"],
            "conversation-edits")

    def test_vision_flag_only_with_image_content(self) -> None:
        plain = copilot_dynamic_headers({"messages": [{"role": "user", "content": "hi"}]})
        self.assertNotIn("Copilot-Vision-Request", plain)
        vision = copilot_dynamic_headers({"messages": [{"role": "user", "content": [
            {"type": "text", "text": "look"}, {"type": "image_url", "image_url": {"url": "data:x"}}]}]})
        self.assertEqual(vision["Copilot-Vision-Request"], "true")

    def test_google_headers_carry_key_both_ways(self) -> None:
        h = google_headers("k-123")
        self.assertEqual(h["Authorization"], "Bearer k-123")
        self.assertEqual(h["x-goog-api-key"], "k-123")

    def test_gateway_sends_copilot_fingerprint_and_token_headers(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        qm = QuotaManager(REPO_ROOT / "proxy_gateway" / "quota_policy.yaml", Path(tmp.name) / "l.db")
        captured = {}

        def upstream(request: httpx.Request) -> httpx.Response:
            if request.url.host.startswith("api.individual.githubcopilot.com"):
                captured.update(dict(request.headers))
                captured["host"] = request.url.host
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}], "usage": {}})

        auth = CopilotAuth(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"token": TOKEN, "expires_at": FUTURE})))
        import os
        os.environ["HARNESS_COPILOT_GITHUB_TOKEN"] = "gho_test"
        original = provider_auth._COPILOT
        provider_auth._COPILOT = auth
        try:
            now = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)  # off-peak, last-option pool
            # Copilot sits in the last-option reserve: only reachable once all primary pools are spent.
            qm.record_usage("zhipu-glm-5.3", units_override=30000.0, now_utc=now)
            qm.record_usage("kimi-k3.1-pro", units_override=2000.0, now_utc=now)
            qm.record_usage("opencode-deepseek-v4.1-flash", units_override=60.0, now_utc=now)
            qm.record_usage("google-ai-gemini-4-neon", units_override=999.0, now_utc=now)  # skip the other reserve
            client = TestClient(create_app(transport=httpx.MockTransport(upstream), quota_manager=qm,
                                           now_provider=lambda: now))
            resp = client.post("/v1/chat/completions", json={
                "model": "copilot-claude-sonnet-5.5", "stream": False,
                "messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]})
        finally:
            provider_auth._COPILOT = original
            del os.environ["HARNESS_COPILOT_GITHUB_TOKEN"]
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(captured["host"], "api.individual.githubcopilot.com")
        self.assertEqual(captured["copilot-integration-id"], "vscode-chat")
        self.assertEqual(captured["editor-version"], "vscode/1.107.0")
        self.assertEqual(captured["x-initiator"], "agent")
        self.assertTrue(captured["authorization"].startswith("Bearer tid=abc"))
