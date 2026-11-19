"""Sub-agent dispatch: execute one subtask through the local proxy gateway.

The gateway assigns the cognitive tier via the X-Harness-Agent-Id profile,
selects the model dynamically (quota/peak/failover), injects the thinking
policy, and enforces the output contract. This module only builds payloads and
parses results — the main agent never touches implementation details.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

DEFAULT_GATEWAY_URL = "http://127.0.0.1:8787"

SUBAGENT_PREAMBLE = (
    "You are a harness sub-agent executing ONE delegated subtask. "
    "Follow the Epistemic & Dual-Process Governance Harness: lowest viable tier, "
    "L1/L2/L3 separation, stop-loss on missing evidence. "
    "Return only the subtask result with its evidence tier tags; do not speculate beyond scope."
)


_BIAS_GUARD = None


def _get_bias_guard():
    from .bias_guard import BiasGuard

    global _BIAS_GUARD
    if _BIAS_GUARD is None:
        repo_root = Path(__file__).resolve().parent.parent
        _BIAS_GUARD = BiasGuard(repo_root / "knowledge" / "l3_heuristics" / "cognitive_biases.yaml")
    return _BIAS_GUARD


def dispatch_subtask(
    agent_profile: str,
    task_text: str,
    context: str = "",
    task_id: str = "default",
    gateway_url: str | None = None,
    attached_skills: list[dict[str, Any]] | None = None,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 300.0,
    escalate_on_bias: bool = False,
) -> dict[str, Any]:
    """Dispatch a single subtask to the gateway with the given agent profile."""
    base = (gateway_url or os.getenv("HARNESS_GATEWAY_URL", DEFAULT_GATEWAY_URL)).rstrip("/")
    system_parts = [SUBAGENT_PREAMBLE]
    for skill in attached_skills or []:
        system_parts.append(f"[Attached Skill: {skill.get('name', skill.get('id', 'unknown'))}]\n{skill.get('content', '')}")
    user_content = task_text if not context else f"{task_text}\n\n[Controller context]\n{context}"

    payload: dict[str, Any] = {
        "stream": False,
        "messages": [
            {"role": "system", "content": "\n\n".join(system_parts)},
            {"role": "user", "content": user_content},
        ],
    }
    headers = {
        "X-Harness-Agent-Id": agent_profile,
        "X-Harness-Session-Id": task_id,
        "Content-Type": "application/json",
    }
    with httpx.Client(transport=transport, timeout=timeout) as client:
        resp = client.post(f"{base}/v1/chat/completions", json=payload, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    message = (data.get("choices") or [{}])[0].get("message") or {}
    content = message.get("content", "")
    result = {
        "agent_profile": agent_profile,
        "task_id": task_id,
        "content": content,
        "routed_tier": resp.headers.get("X-Harness-Routed-Tier", ""),
        "selected_model": resp.headers.get("X-Harness-Selected-Model", ""),
        "tier_tag": resp.headers.get("X-Harness-Tier-Tag", ""),
        "usage": data.get("usage") or {},
        "bias_scan": _get_bias_guard().scan(content),
    }
    # L3 first-pass escalation: bias hits are re-dispatched to a cross-family critic pass.
    if escalate_on_bias and result["bias_scan"]["matches"]:
        verdict = dispatch_subtask(
            agent_profile="critic",
            task_text=(
                "critic review (bias screen): the sub-agent result below hit bias markers "
                f"{[m['bias_id'] for m in result['bias_scan']['matches']]}. "
                "Audit for overclaiming beyond upstream evidence tier, missing counter-examples, "
                "and tier-tag compliance. Verdict format: PASS / FAIL + one-line reason.\n\n"
                + content
            ),
            context=context,
            task_id=f"{task_id}-critic",
            gateway_url=gateway_url,
            transport=transport,
            timeout=timeout,
        )
        result["critic_verdict"] = verdict["content"].strip()
    return result
