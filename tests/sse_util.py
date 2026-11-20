"""Shared test helper: build OpenAI-compatible SSE responses for mocked upstreams."""

from __future__ import annotations

import json

import httpx


def sse_response(
    content: str,
    *,
    headers: dict[str, str] | None = None,
    usage: dict | None = None,
    model: str = "mock",
) -> httpx.Response:
    """Return a 200 streamable response shaped like the gateway's SSE output."""
    chunks = [
        {"id": "c1", "model": model, "choices": [{"index": 0, "delta": {"content": content}}]},
    ]
    if usage:
        chunks.append({"id": "c1", "model": model, "choices": [], "usage": usage})
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    base_headers = {
        "X-Harness-Routed-Tier": "system_1_5",
        "X-Harness-Selected-Model": model,
        "X-Harness-Tier-Tag": "[Tier: Structured Analysis (Tier 1.5) | Mode: Converge]",
        "content-type": "text/event-stream",
    }
    base_headers.update(headers or {})
    return httpx.Response(200, text=body, headers=base_headers)
