"""Output-Contract Tier-Tag Validator & Injector (response-boundary enforcement).

The harness output contract (SKILL.md / AGENTS.md §3) requires every
user-facing answer to begin with a `[Tier: ... | Mode: ...]` tag. Compliant
models already emit it; this guard hard-enforces the contract at the gateway
boundary: when the upstream response omits the tag, the canonical tag derived
from the routing decision is injected. Compliant responses pass through
untouched. Injection events are traced for auditability.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

TIER_LABELS: dict[str, str] = {
    "system_0": "Reflexive Execution (Tier 0)",
    "system_1": "Fast Intuition (Tier 1)",
    "system_1_5": "Structured Analysis (Tier 1.5)",
    "system_2": "Deliberative Derivation (Tier 2)",
    "system_2_plus": "Metacognitive Critic (Tier 2+)",
}

CONVERGE_PATTERNS = re.compile(r"(收敛|converge|审计|audit|结论|拍板|复核|critic)", re.I)
EXPLORE_PATTERNS = re.compile(r"(探索|发散|头脑风暴|brainstorm|explore|初筛|点子)", re.I)

LEADING_TAG_RE = re.compile(r"^\s*\[Tier:[^\]\n]*\]")


def detect_mode(user_text: str, tier: str) -> str:
    """Infer Explore/Converge mode from the last user message (keyword heuristic, L3)."""
    if CONVERGE_PATTERNS.search(user_text or ""):
        return "Converge"
    if EXPLORE_PATTERNS.search(user_text or ""):
        return "Explore"
    # Default: only the deliberative tiers converge; routine analysis stays exploratory.
    return "Converge" if tier in ("system_2", "system_2_plus") else "Explore"


def build_tier_tag(tier: str, mode: str) -> str:
    label = TIER_LABELS.get(tier, tier)
    return f"[Tier: {label} | Mode: {mode}]"


def ensure_text_tag(text: str, tag: str) -> tuple[str, bool]:
    """Return (text, injected). Inject `tag` when the text lacks a leading tier tag."""
    if not text or not text.strip():
        return text, False
    if LEADING_TAG_RE.match(text):
        return text, False
    return f"{tag}\n\n{text.lstrip()}", True


def guard_openai_message(data: dict, tag: str) -> bool:
    """Ensure the first assistant message in a non-streaming OpenAI response starts with the tag."""
    try:
        msg = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return False
    if msg.get("tool_calls") and not (msg.get("content") or "").strip():
        return False  # pure tool-call turn: no user-facing text, do not inject
    content = msg.get("content")
    if not isinstance(content, str):
        return False
    new_text, injected = ensure_text_tag(content, tag)
    if injected:
        msg["content"] = new_text
    return injected


def guard_openai_stream_delta(delta: dict, tag: str) -> bool:
    """Prepend the tag to the first non-empty content delta of an OpenAI SSE stream."""
    content = delta.get("content")
    if not isinstance(content, str) or not content:
        return False
    new_text, injected = ensure_text_tag(content, tag)
    if injected:
        delta["content"] = new_text
    return injected


def guard_anthropic_content(data: dict, tag: str) -> bool:
    """Ensure the first text block in a non-streaming Anthropic response starts with the tag."""
    content = data.get("content")
    if not isinstance(content, list) or not content:
        return False
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str) and block["text"].strip():
            new_text, injected = ensure_text_tag(block["text"], tag)
            if injected:
                block["text"] = new_text
            return injected
    # Pure tool_use turns carry no user-facing text: leave them untouched.
    return False


def guard_anthropic_stream_delta(delta: dict, tag: str) -> bool:
    """Prepend the tag to the first non-empty text_delta of an Anthropic SSE stream."""
    if delta.get("type") != "text_delta":
        return False
    text = delta.get("text")
    if not isinstance(text, str) or not text:
        return False
    new_text, injected = ensure_text_tag(text, tag)
    if injected:
        delta["text"] = new_text
    return injected


@dataclass
class StreamTagGuard:
    """Stateful SSE prefix buffer preventing split-chunk duplicate `[Tier: ...]` tags.

    Upstream may split the tag across chunks ("[" + "Tier: ...]"); a stateless
    per-chunk check then injects a second copy. This buffer decides exactly once.
    """

    tag: str
    max_probe_chars: int = 24
    _buf: str = ""
    _decided: bool = False
    injected: bool = False

    def feed(self, chunk: str) -> str | None:
        """Feed a content delta; returns text to emit, or None while still probing the prefix."""
        if self._decided:
            return chunk
        if not chunk:
            return None
        self._buf += chunk
        stripped = self._buf.lstrip()
        if not stripped:
            return None
        if not stripped.startswith("["):
            # No leading tag marker: inject the canonical tag and flush the buffer once.
            self._decided = True
            self.injected = True
            out = self.tag + "\n\n" + stripped
            self._buf = ""
            return out
        if ("\n" in stripped) or ("]" in stripped) or len(stripped) >= self.max_probe_chars:
            self._decided = True
            out, self.injected = ensure_text_tag(self._buf, self.tag)
            self._buf = ""
            return out
        return None

    def flush(self) -> str | None:
        """Emit any buffered prefix if the stream ended before a decision was made."""
        if self._decided or not self._buf:
            return None
        self._decided = True
        out, self.injected = ensure_text_tag(self._buf, self.tag)
        self._buf = ""
        return out
