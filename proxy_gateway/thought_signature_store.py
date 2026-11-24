"""Thought-signature round trip for Gemini via the OpenAI-compatible endpoint.

Gemini 3 returns a signature on each tool call (``extra_content.google.thought_signature``)
and rejects the follow-up request with HTTP 400 when it is missing. Clients that drop
unknown fields never send it back, so the gateway records signatures from streamed
tool-call chunks and re-attaches them before forwarding the next request.

Scope: Google ``generativelanguage`` upstreams on the OpenAI route only.
Counter-example: a client that already round-trips the field is left untouched.
Matching is by tool-call id only (ids are provider-generated and unique), so entries from
other sessions can never be attached. Single-threaded asyncio: no lock needed.
"""

from __future__ import annotations

from collections import deque
from typing import Any

_SIG_KEY_PART = "thought_signature"


def _find_signature(obj: Any) -> str | None:
    """Depth-first search for a thought_signature string (tolerates wrapper variants)."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if _SIG_KEY_PART in key and isinstance(value, str) and value:
                return value
            hit = _find_signature(value)
            if hit:
                return hit
    elif isinstance(obj, list):
        for value in obj:
            hit = _find_signature(value)
            if hit:
                return hit
    return None


class ThoughtSignatureStore:
    """Bounded, most-recent-first map of tool-call id -> signature."""

    def __init__(self, capacity: int = 512) -> None:
        self._capacity = capacity
        self._entries: deque[dict[str, Any]] = deque(maxlen=capacity)

    def record_chunk(self, chunk: dict[str, Any]) -> None:
        for choice in chunk.get("choices") or []:
            part = choice.get("delta") or choice.get("message") or {}  # stream / non-stream
            for call in part.get("tool_calls") or []:
                if not isinstance(call, dict) or not call.get("id"):
                    continue
                sig = _find_signature(call.get("extra_content"))
                if sig:
                    self._entries.appendleft({"id": call["id"], "sig": sig})

    def inject(self, body: dict[str, Any]) -> int:
        """Attach missing signatures to assistant tool_calls; returns the number attached."""
        attached = 0
        for msg in body.get("messages") or []:
            for call in (msg.get("tool_calls") if isinstance(msg, dict) else None) or []:
                if not isinstance(call, dict) or _find_signature(call.get("extra_content")):
                    continue
                sig = self._lookup(call.get("id"))
                if sig:
                    extra = call.get("extra_content")
                    call["extra_content"] = extra if isinstance(extra, dict) else {}
                    call["extra_content"]["google"] = {"thought_signature": sig}
                    attached += 1
        return attached

    def _lookup(self, call_id: Any) -> str | None:
        if call_id:
            for entry in self._entries:
                if entry["id"] == call_id:
                    return str(entry["sig"])
        return None


thought_signature_store = ThoughtSignatureStore()
