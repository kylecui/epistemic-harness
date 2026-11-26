"""Sub-agent dispatch: execute one subtask through the local proxy gateway.

Design notes:
  - Every dispatch rides the gateway's SSE stream (stream=True) so sub-agents get the
    streaming thrashing guard and its seamless low-effort recovery (P0-3). Non-streaming
    would silently bypass that guard and hang for the full timeout instead.
  - Cross-family critic: the drafter's model is passed as X-Harness-Exclude-Model so the
    gateway physically excludes the drafter's shared pool (P0-1) — session-id scoping alone
    does not work for per-subtask session ids.
  - Sub-agents have NO tools: they reason in plain text; the controller applies side effects.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

import httpx

DEFAULT_GATEWAY_URL = "http://127.0.0.1:8787"

SUBAGENT_PREAMBLE = (
    "You are a harness sub-agent executing ONE delegated subtask. "
    "Follow the Epistemic & Dual-Process Governance Harness: lowest viable tier, "
    "L1/L2/L3 separation, stop-loss on missing evidence. "
    "You have NO tools and cannot read, write, run or inspect anything — never emit tool-call "
    "markup (DSML/XML/JSON function calls); the controller performs all side effects. "
    "Return only the subtask result as plain text/markdown with its evidence tier tags; "
    "do not speculate beyond scope."
)

# Reasoning-heavy models can burn the whole output budget on reasoning_content; keep
# generous budgets for deep tiers and retry with a clamped effort when content comes back empty.
BUDGET_BY_PROFILE: dict[str, int] = {
    "explorer": 2048,
    "coder": 4096,
    "deep": 8192,
    "critic": 8192,
}

# Empty-content retries may reduce effort only within each profile's C1 contract.
RETRY_EFFORTS: dict[str, tuple[str, str]] = {
    "coder": ("low", "low"),
    "deep": ("medium", "medium"),
    "critic": ("medium", "medium"),
}

_BIAS_GUARD = None


def _record_dispatch(
    agent_profile: str, task_id: str, task_text: str, result: dict[str, Any], attempts: int,
    category: str | None = None,
) -> None:
    """Append one authoritative dispatch record to traces/dispatches.jsonl.

    The extension log sees tool-call text and often cannot extract routing
    metadata from wrapped results; here the gateway's own response headers are
    the source of truth, so every dispatch is traceable end to end.
    """
    try:
        repo_root = Path(__file__).resolve().parent.parent
        traces_dir = Path(os.environ.get("HARNESS_TRACES_DIR") or (repo_root / "traces"))
        path = traces_dir / "dispatches.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "task_id": task_id,
            "profile": agent_profile,
            "category": category or result.get("category") or "",
            "task_text": (task_text or "")[:200],
            "routed_tier": result.get("routed_tier", ""),
            "selected_model": result.get("selected_model", ""),
            "tier_tag": result.get("tier_tag", ""),
            "effort": result.get("effort", ""),
            "attempts": attempts,
            "prompt_tokens": (result.get("usage") or {}).get("prompt_tokens"),
            "completion_tokens": (result.get("usage") or {}).get("completion_tokens"),
            "bias_matches": [m.get("bias_id") for m in (result.get("bias_scan") or {}).get("matches") or []],
            "critic_model": result.get("critic_model", ""),
        }
        for extra_key in ("tools_used", "rounds", "elapsed_sec", "runner", "via"):
            if extra_key in result:
                record[extra_key] = result[extra_key]
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass  # tracing must never break the dispatch


def _get_bias_guard():
    from .bias_guard import BiasGuard

    global _BIAS_GUARD
    if _BIAS_GUARD is None:
        repo_root = Path(__file__).resolve().parent.parent
        _BIAS_GUARD = BiasGuard(repo_root / "knowledge" / "l3_heuristics" / "cognitive_biases.yaml")
    return _BIAS_GUARD


def _consume_openai_sse(resp: httpx.Response) -> tuple[str, dict[str, Any]]:
    """Accumulate assistant text + usage from an OpenAI-compatible SSE stream."""
    parts: list[str] = []
    usage: dict[str, Any] = {}
    for raw in resp.iter_lines():
        if not raw:
            continue
        line = raw.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(obj.get("usage"), dict):
            usage = obj["usage"] or usage
        for choice in obj.get("choices") or []:
            delta = (choice or {}).get("delta") or {}
            text = delta.get("content")
            if isinstance(text, str) and text:
                parts.append(text)
    return "".join(parts), usage


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
    exclude_model: str | None = None,
    max_tokens: int | None = None,
    model: str | None = None,
    effort: str | None = None,
    category: str | None = None,
    attachments: list[str] | None = None,
) -> dict[str, Any]:
    """Dispatch a single subtask to the gateway under the given agent profile.

    `attachments` (issue #26) are image paths: they become image_url blocks after the task text so a
    vision-capable model can look at them. The caller routes by capability; this layer only carries.
    """
    base = (gateway_url or os.getenv("HARNESS_GATEWAY_URL", DEFAULT_GATEWAY_URL)).rstrip("/")
    system_parts = [SUBAGENT_PREAMBLE]
    for skill in attached_skills or []:
        system_parts.append(f"[Attached Skill: {skill.get('name', skill.get('id', 'unknown'))}]\n{skill.get('content', '')}")
    user_content = task_text if not context else f"{task_text}\n\n[Controller context]\n{context}"
    if attachments:
        from orchestrator.vision import build_content, read_image
        images = [read_image(path) for path in attachments]
        user_content = build_content(user_content, images)

    budget = max_tokens or BUDGET_BY_PROFILE.get(agent_profile, 4096)
    payload: dict[str, Any] = {
        "stream": True,  # P0-3: ride the streaming guard (thrashing circuit-breaker + recovery)
        "max_tokens": budget,
        "messages": [
            {"role": "system", "content": "\n\n".join(system_parts)},
            {"role": "user", "content": user_content},
        ],
    }
    if model:
        payload["model"] = model  # pin: gateway prioritizes it in select_candidates
    headers = {
        "X-Harness-Agent-Id": agent_profile,
        "X-Harness-Session-Id": task_id,
        "Content-Type": "application/json",
    }
    if effort:
        headers["X-Harness-Effort"] = effort  # hint; gateway clamps to the model's max_effort
    if exclude_model:
        headers["X-Harness-Exclude-Model"] = exclude_model

    content = ""
    usage: dict[str, Any] = {}
    routed_tier = selected_model = tier_tag = effort = ""
    attempts = 0
    while True:
        attempts += 1
        with httpx.Client(transport=transport, timeout=timeout) as client:
            with client.stream("POST", f"{base}/v1/chat/completions", json=payload, headers=headers) as resp:
                if resp.status_code >= 400:
                    body = resp.read().decode("utf-8", errors="replace")
                    raise httpx.HTTPStatusError(
                        f"gateway {resp.status_code}: {body[:300]}", request=resp.request, response=resp
                    )
                content, usage = _consume_openai_sse(resp)
                routed_tier = resp.headers.get("X-Harness-Routed-Tier", "")
                selected_model = resp.headers.get("X-Harness-Selected-Model", "")
                tier_tag = resp.headers.get("X-Harness-Tier-Tag", "")
                effort = resp.headers.get("X-Harness-Effort", "")
        if content.strip() or attempts >= 3:
            break
        # Empty assistant text: the model spent the entire budget on reasoning. Clamp and retry.
        payload["max_tokens"] = min(int(payload["max_tokens"]) * 2, 16384)
        retries = RETRY_EFFORTS.get(agent_profile, ("low", "minimal"))
        headers["X-Harness-Effort"] = retries[min(attempts - 1, 1)]

    result = {
        "agent_profile": agent_profile,
        "task_id": task_id,
        "content": content,
        "routed_tier": routed_tier,
        "selected_model": selected_model,
        "tier_tag": tier_tag,
        "effort": effort,
        "usage": usage or {},
        "bias_scan": _get_bias_guard().scan(content),
    }
    _record_dispatch(agent_profile, task_id, task_text, result, attempts, category=category)
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
            exclude_model=selected_model or None,  # P0-1: never let the drafter's family review itself
        )
        result["critic_verdict"] = verdict["content"].strip()
        result["critic_model"] = verdict["selected_model"]
    return result
