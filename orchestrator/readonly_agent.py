"""Read-only agent loop (G13): a sub-agent that can look but cannot touch.

The model talks to the gateway; when it wants evidence it emits a JSON tool
call, we execute it inside the declared workdir sandbox, feed the result back,
and continue. The loop is capped: no runaway tool-calling, every round is one
gateway request.

Stop conditions:
  * the model's reply contains no tool call  -> final answer;
  * max_rounds exhausted                     -> truncated answer with a note.

Every run is recorded in traces/dispatches.jsonl with profile "explorer-ro"
and the tools it used — the same observability contract as other dispatches.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import time
from typing import Any

import httpx

from orchestrator.dispatch import _consume_openai_sse, _record_dispatch
from orchestrator.readonly_tools import TOOL_SPECS, execute_tool

DEFAULT_GATEWAY_URL = "http://127.0.0.1:8787"

PREAMBLE = (
    "You are a read-only explorer sub-agent. You can inspect the workspace with tools, "
    "but you cannot write, delete, or execute anything. "
    "When you need evidence, emit EXACTLY one tool call as a ```json fenced block:\n"
    '```json\n{"tool": "grep", "args": {"pattern": "...", "path": "..."}}\n```\n'
    "Available tools:\n"
    + json.dumps(TOOL_SPECS, ensure_ascii=False, indent=1)
    + "\nRules: at most one tool call per reply; paths are relative to the workdir; "
    "when you have enough evidence, answer directly in plain text with file:line cites. "
    "Do not narrate tool calls outside the JSON block."
)

_TOOL_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)
_TOOL_LINE_RE = re.compile(r'^\s*\{\s*"tool"\s*:', re.M)


def parse_tool_call(content: str) -> dict[str, Any] | None:
    """Extract one tool call from the model reply, if present."""
    m = _TOOL_BLOCK_RE.search(content or "")
    candidate = m.group(1) if m else None
    if candidate is None:
        m2 = _TOOL_LINE_RE.search(content or "")
        if m2:
            candidate = content[m2.start():].strip()
    if not candidate:
        return None
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if isinstance(obj, dict) and isinstance(obj.get("tool"), str):
        return {"tool": obj["tool"], "args": obj.get("args") or {}}
    return None


def _gateway_round(
    messages: list[dict[str, str]], effort: str | None, model: str | None, budget: int,
    timeout: float, transport: httpx.BaseTransport | None,
) -> tuple[str, dict[str, Any]]:
    base = (os.getenv("HARNESS_GATEWAY_URL", DEFAULT_GATEWAY_URL)).rstrip("/")
    payload: dict[str, Any] = {
        "stream": True, "max_tokens": budget, "messages": messages,
    }
    if model:
        payload["model"] = model
    headers = {"X-Harness-Agent-Id": "explorer", "Content-Type": "application/json"}
    if effort:
        headers["X-Harness-Effort"] = effort
    with httpx.Client(transport=transport, timeout=timeout) as client:
        with client.stream("POST", f"{base}/v1/chat/completions", json=payload, headers=headers) as resp:
            if resp.status_code >= 400:
                body = resp.read().decode("utf-8", errors="replace")
                raise httpx.HTTPStatusError(f"gateway {resp.status_code}: {body[:300]}",
                                            request=resp.request, response=resp)
            content, usage = _consume_openai_sse(resp)
            meta = {
                "routed_tier": resp.headers.get("X-Harness-Routed-Tier", ""),
                "selected_model": resp.headers.get("X-Harness-Selected-Model", ""),
                "tier_tag": resp.headers.get("X-Harness-Tier-Tag", ""),
                "effort": resp.headers.get("X-Harness-Effort", ""),
            }
    return content, {"usage": usage, **meta}


def dispatch_readonly(
    task_text: str,
    workdir: Path | str,
    task_id: str = "ro-1",
    max_rounds: int = 6,
    budget: int = 2048,
    timeout: float = 120.0,
    effort: str | None = "low",
    model: str | None = None,
    category: str | None = None,
    transport: httpx.BaseTransport | None = None,
    runner: str = "",
    via: str = "",
) -> dict[str, Any]:
    root = Path(workdir).resolve()
    messages: list[dict[str, str]] = [
        {"role": "system", "content": PREAMBLE},
        {"role": "user", "content": task_text},
    ]
    tools_used: list[dict[str, Any]] = []
    started = time.perf_counter()
    content = ""
    meta: dict[str, Any] = {}
    rounds = 0

    for rounds in range(1, max_rounds + 1):
        content, meta = _gateway_round(messages, effort, model, budget, timeout, transport)
        call = parse_tool_call(content)
        if call is None:
            break
        result = execute_tool(root, call["tool"], call["args"])
        tools_used.append({"tool": call["tool"], "args": call["args"], "round": rounds})
        messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": f"[tool result: {call['tool']}]\n{result}"})
    else:
        content += f"\n\n[round cap {max_rounds} reached; answer may be incomplete]"

    elapsed = round(time.perf_counter() - started, 3)
    result = {
        "agent_profile": "explorer-ro",
        "task_id": task_id,
        "content": content,
        "tools_used": tools_used,
        "rounds": rounds,
        "elapsed_sec": elapsed,
        "bias_scan": {"matches": []},
        "category": category or "exploration",
        # issue #7: name the plane that executed this run, so the trace is auditable
        "runner": runner,
        "via": via,
    }
    result.update({k: meta.get(k, "") for k in ("routed_tier", "selected_model", "tier_tag", "effort")})
    result["usage"] = meta.get("usage") or {}
    _record_dispatch("explorer-ro", task_id, task_text, result, attempts=1, category=result["category"])
    result["tools_used"] = tools_used
    return result
