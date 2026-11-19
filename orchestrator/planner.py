"""Deterministic task classifier: maps a task text to a cognitive tier and sub-agent profile.

The main agent stays the reasoner (it decides decomposition); this classifier is
an advisory L2-level aid that reuses the gateway's fingerprint router, so the
suggested profile always matches what the gateway would enforce anyway.
"""

from __future__ import annotations

from typing import Any

from proxy_gateway.policy import decide_routing
from proxy_gateway.response_guard import detect_mode

TIER_TO_AGENT_PROFILE: dict[str, str] = {
    "system_0": "explorer",
    "system_1": "explorer",
    "system_1_5": "coder",
    "system_2": "deep",
    "system_2_plus": "critic",
}


def classify_task(task_text: str, skills_matcher: Any = None) -> dict[str, Any]:
    decision = decide_routing([{"role": "user", "content": task_text}])
    skills: list[dict[str, Any]] = []
    if skills_matcher is not None:
        skills = [
            {"id": s["id"], "name": s["name"], "description": s["description"], "tier_hint": s.get("tier_hint")}
            for s in skills_matcher(task_text)
        ]
    return {
        "task": task_text,
        "tier": decision.tier,
        "reasoning_effort": decision.openai_effort,
        "mode": detect_mode(task_text, decision.tier),
        "agent_profile": TIER_TO_AGENT_PROFILE[decision.tier],
        "routing_reason": decision.reason,
        "auto_attached_skills": skills,
    }
