"""Gateway payload sanitization guards (Google 400 `Unknown name "store"`)."""

from __future__ import annotations

import unittest

from proxy_gateway.policy import sanitize_openai_payload


class SanitizeOpenaiPayloadTests(unittest.TestCase):
    def test_strips_client_only_fields_for_non_openai_upstream(self):
        payload = {
            "model": "gemini-x",
            "store": False,
            "previous_response_id": "resp_1",
            "prompt_cache_key": "k",
            "messages": [{"role": "user", "content": "hi"}],
        }
        out = sanitize_openai_payload(payload, "https://generativelanguage.googleapis.com/v1beta/openai")
        for field in ("store", "previous_response_id", "prompt_cache_key"):
            self.assertNotIn(field, out)
        self.assertIn("messages", out)
        # original untouched (derived payloads stay consistent)
        self.assertIn("store", payload)

    def test_keeps_fields_for_openai_upstream(self):
        payload = {"model": "gpt-x", "store": False}
        out = sanitize_openai_payload(payload, "https://api.openai.com/v1")
        self.assertIn("store", out)

    def test_derived_retry_payload_stays_clean(self):
        base = sanitize_openai_payload({"model": "m", "store": False}, "https://api.individual.githubcopilot.com")
        retry = dict(base)
        retry["messages"] = []
        self.assertNotIn("store", retry)


if __name__ == "__main__":
    unittest.main()
