"""Adaptive Dual-Process Cognitive Router (System 0 -> System 2+ Cross-Family Critic)."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class RoutingDecision:
    tier: str
    openai_effort: str
    anthropic_budget: int
    max_thinking_chars: int
    max_pivots: int
    cross_family_critic: bool
    reason: str


TIER_PROFILES: dict[str, tuple[str, int, int, int, bool]] = {
    # tier: (openai_effort, anthropic_budget, max_thinking_chars, max_pivots, cross_family_critic)
    # Relaxed v1.1: normal thinking depth is governed upstream by reasoning_effort / budget_tokens;
    # max_thinking_chars here only feeds the extreme runaway cap (3x, floor 45k).
    "system_0":      ("low",    0,     2400, 2, False),
    "system_1":      ("low",    2048,  6000, 3, False),
    "system_1_5":    ("medium", 6144,  18000, 4, False),
    "system_2":      ("high",   16384, 36000, 6, False),
    "system_2_plus": ("high",   16384, 36000, 6, True),
}

SYSTEM_0_PATTERNS = re.compile(
    r"(转成|转换|格式化|camelCase|snake_case|JSON\s*key|直接给我结果|一行命令|翻译成\s*shell)",
    re.I,
)
SYSTEM_2_PLUS_PATTERNS = re.compile(
    r"(独立复核|开启审计|复核前文|挑刺|元认知审计|交叉审计|critic)",
    re.I,
)
SYSTEM_2_PATTERNS = re.compile(
    r"(CAP\s*定理|第一性原理|形式化证明|收敛态|审计|CEO|拍板|不可逆|网络分区)",
    re.I,
)
SYSTEM_1_PATTERNS = re.compile(
    r"(探索态|发散|头脑风暴|点子|初筛|快速列出)",
    re.I,
)


def _extract_last_user_text(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return " ".join(
                    b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
                )
    return ""


def decide_routing(
    messages: list[dict[str, Any]],
    headers: dict[str, str] | None = None,
    agent_tier: str | None = None,
) -> RoutingDecision:
    """Route a request to a cognitive tier.

    Precedence: explicit ``X-Harness-Tier`` header > ``agent_tier`` (resolved
    from the ``X-Harness-Agent-Id`` profile) > task fingerprint > default.
    """
    hdrs = {k.lower(): v.strip().lower() for k, v in (headers or {}).items()}
    user_text = _extract_last_user_text(messages)

    explicit = hdrs.get("x-harness-tier")
    if explicit in TIER_PROFILES:
        eff, bud, mchars, mpiv, cf = TIER_PROFILES[explicit]
        return RoutingDecision(explicit, eff, bud, mchars, mpiv, cf, f"header_override:{explicit}")

    agent = (agent_tier or "").strip().lower()
    if agent in TIER_PROFILES:
        eff, bud, mchars, mpiv, cf = TIER_PROFILES[agent]
        return RoutingDecision(agent, eff, bud, mchars, mpiv, cf, f"agent_profile:{agent}")

    if re.search(r"\[(R0|System\s*0)\]|直觉执行档", user_text, re.I):
        eff, bud, mchars, mpiv, cf = TIER_PROFILES["system_0"]
        return RoutingDecision("system_0", eff, bud, mchars, mpiv, cf, "prompt_tag:system_0")

    if len(user_text) <= 220 and SYSTEM_0_PATTERNS.search(user_text):
        eff, bud, mchars, mpiv, cf = TIER_PROFILES["system_0"]
        return RoutingDecision("system_0", eff, bud, mchars, mpiv, cf, "fingerprint:deterministic_simple")

    if SYSTEM_2_PLUS_PATTERNS.search(user_text):
        eff, bud, mchars, mpiv, cf = TIER_PROFILES["system_2_plus"]
        return RoutingDecision("system_2_plus", eff, bud, mchars, mpiv, cf, "fingerprint:cross_family_critic")

    if SYSTEM_2_PATTERNS.search(user_text):
        eff, bud, mchars, mpiv, cf = TIER_PROFILES["system_2"]
        return RoutingDecision("system_2", eff, bud, mchars, mpiv, cf, "fingerprint:high_bar_trigger")

    if SYSTEM_1_PATTERNS.search(user_text):
        eff, bud, mchars, mpiv, cf = TIER_PROFILES["system_1"]
        return RoutingDecision("system_1", eff, bud, mchars, mpiv, cf, "fingerprint:explore_fast")

    eff, bud, mchars, mpiv, cf = TIER_PROFILES["system_1_5"]
    return RoutingDecision("system_1_5", eff, bud, mchars, mpiv, cf, "default:system_1_5")


def rewrite_openai_payload(payload: dict[str, Any], decision: RoutingDecision) -> dict[str, Any]:
    updated = dict(payload)
    updated["reasoning_effort"] = decision.openai_effort
    return updated


def rewrite_anthropic_payload(payload: dict[str, Any], decision: RoutingDecision) -> dict[str, Any]:
    updated = dict(payload)
    if decision.anthropic_budget <= 0:
        updated["thinking"] = {"type": "disabled"}
    else:
        updated["thinking"] = {"type": "enabled", "budget_tokens": decision.anthropic_budget}
    return updated

THINKING_EN_DIRECTIVE = (
    "[Harness Thinking Policy] Conduct internal reasoning/thinking in concise English "
    "(keep domain-specific non-English terms verbatim when needed to prevent translation loss). "
    "Always write the final user-facing answer strictly in the user's language."
)


def inject_thinking_language_openai(payload: dict[str, Any], mode: str = "en_with_native_terms") -> dict[str, Any]:
    if mode == "auto":
        return payload
    updated = dict(payload)
    msgs = list(updated.get("messages") or [])
    if msgs and msgs[0].get("role") == "system" and isinstance(msgs[0].get("content"), str):
        if "[Harness Thinking Policy]" not in msgs[0]["content"]:
            msgs[0] = {**msgs[0], "content": THINKING_EN_DIRECTIVE + "\n\n" + msgs[0]["content"]}
    else:
        msgs.insert(0, {"role": "system", "content": THINKING_EN_DIRECTIVE})
    updated["messages"] = msgs
    return updated


def inject_thinking_language_anthropic(payload: dict[str, Any], mode: str = "en_with_native_terms") -> dict[str, Any]:
    if mode == "auto":
        return payload
    updated = dict(payload)
    existing = updated.get("system")
    if isinstance(existing, str):
        if "[Harness Thinking Policy]" not in existing:
            updated["system"] = THINKING_EN_DIRECTIVE + "\n\n" + existing
    elif isinstance(existing, list):
        updated["system"] = [{"type": "text", "text": THINKING_EN_DIRECTIVE}, *existing]
    else:
        updated["system"] = THINKING_EN_DIRECTIVE
    return updated

