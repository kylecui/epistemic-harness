"""Streaming Anti-Thrashing Guard with Seamless Low-Reasoning Recovery.

Design principle:
  1. Prevention first: normal thinking length is controlled upstream via `reasoning_effort`
     and `thinking.budget_tokens`, NOT by brutally killing healthy streams mid-thought.
  2. True thrashing detection: only trips on repeated ungrounded self-doubt pivots
     ("Wait, but... Actually, wait... Let me reconsider...") or extreme runaway length.
  3. Zero dead-stops: when tripped, the gateway aborts the thrashing stream and seamlessly
     continues work via an automatic low-reasoning recovery call (tool call or stop-loss answer).
"""

from __future__ import annotations

from dataclasses import dataclass
import re

PIVOT_REGEX = re.compile(
    r"(\bwait\s*,?\s*(but|hold on|actually|a second|no)\b"
    r"|\bactually\s*,?\s*wait\b"
    r"|\blet me reconsider\b"
    r"|\bon second thought\b"
    r"|\bhold on\s*,?\s*but\b"
    r"|等等[，,、]?不对"
    r"|不对[，,、]?等等"
    r"|等一下[，,、]?我重新"
    r"|话又说回来)",
    re.I,
)

RECOVERY_DIRECTIVE = (
    "[Harness Auto-Recovery] Your previous thinking stream entered a repetitive self-doubt loop. "
    "Do NOT keep debating internally. Immediately continue the task decisively: either invoke an "
    "MCP/L2 tool to verify missing facts right now, or output your concise actionable conclusion "
    "(confirmed L1/L2 facts, minimal unknown, and 1-3 concrete next actions) in the user's language."
)


@dataclass
class GuardState:
    tier: str
    max_thinking_chars: int
    max_pivots: int
    thinking_chars: int = 0
    pivot_count: int = 0
    tripped: bool = False
    auto_recovered: bool = False
    trip_reason: str | None = None
    _tail_window: str = ""

    def feed_thinking(self, chunk: str) -> bool:
        if self.tripped or not chunk:
            return self.tripped

        self.thinking_chars += len(chunk)
        scan_text = self._tail_window + chunk
        matches = list(PIVOT_REGEX.finditer(scan_text))
        new_pivots = sum(1 for m in matches if m.end() > len(self._tail_window))
        self.pivot_count += new_pivots
        self._tail_window = scan_text[-32:]

        if self.pivot_count >= self.max_pivots:
            self.tripped = True
            self.trip_reason = (
                f"THRASHING_PIVOT_LIMIT: {self.pivot_count} self-doubt pivots "
                f"(limit={self.max_pivots} for {self.tier})."
            )
            return True

        # Only trip on length for extreme runaway (3x tier budget) so normal reasoning is never cut off
        runaway_cap = max(self.max_thinking_chars * 3, 45000)
        if self.thinking_chars >= runaway_cap:
            self.tripped = True
            self.trip_reason = f"RUNAWAY_THINKING_CAP: {self.thinking_chars} chars >= {runaway_cap}."
            return True

        return False
