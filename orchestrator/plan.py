"""Task decomposition & multi-sub-agent execution.

plan_task: deterministic (L3-heuristic) splitter -> subtasks with tier/profile + dependency groups.
run_plan : execute a plan through the gateway — parallel groups run concurrently, dependent
           subtasks receive upstream results as controller context. Each dispatch is an
           ephemeral sub-agent (own profile -> gateway pins tier/model/effort).

Heuristics are deliberately conservative: when no clear structure is detected the plan is a
single subtask (the controller LLM can always pass explicit subtasks to override).
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .dispatch import dispatch_subtask
from .planner import classify_task

_SEQ_MARKERS = re.compile(r"然后|之后再|接着|其次|随后|下一步|最后|then afterwards|and then|finally", re.I)
_LIST_ITEM = re.compile(r"^\s*(?:\d+[.、)]|[（(]\d+[)）]|[-*•]\s+|步骤\s*\d+[:：]?)\s*(.+)$")
_INLINE_ITEM = re.compile(r"(?:^|[\s：:，,。;；])\s*\d+[.、)]\s+")
_CONJ_SPLIT = re.compile(r"\s*(?:；同时|；并且|，以及|，同时|，并且|;\s*also|,\s*and also)\s*")
_MAX_SUBTASKS = 6


def _split_candidates(task_text: str) -> list[tuple[str, list[str]]]:
    """Return [(text, depends_on)] candidates; conservative."""
    lines = [l.strip() for l in task_text.splitlines() if l.strip()]
    listed = [m.group(1).strip() for l in lines if (m := _LIST_ITEM.match(l))]
    listed = [l for l in listed if len(l) >= 6]
    if len(listed) < 2:
        inline = _INLINE_ITEM.split(task_text)
        listed = [p.strip(" 。.；;，,") for p in inline[1:]]
        listed = [l for l in listed if len(l) >= 4]  # CJK is info-dense; 4 chars is a real instruction
    if len(listed) >= 2:
        listed = listed[:_MAX_SUBTASKS]
        chained = bool(_SEQ_MARKERS.search(task_text))
        out: list[tuple[str, list[str]]] = []
        for i, text in enumerate(listed):
            dep = [f"S{i}"] if (chained and i > 0) else []
            out.append((text, dep))
        return out
    parts = [p.strip(" 。.；;，,") for p in _CONJ_SPLIT.split(task_text)]
    parts = [p for p in parts if len(p) >= 8]
    if 2 <= len(parts) <= _MAX_SUBTASKS:
        return [(p, []) for p in parts]
    return [(task_text, [])]


def plan_task(task_text: str, skills_matcher: Any = None) -> dict[str, Any]:
    subtasks: list[dict[str, Any]] = []
    for i, (text, depends_on) in enumerate(_split_candidates(task_text), start=1):
        meta = classify_task(text, skills_matcher=skills_matcher)
        subtasks.append({
            "id": f"S{i}",
            "task_text": text,
            "agent_profile": meta["agent_profile"],
            "tier": meta["tier"],
            "reasoning_effort": meta["reasoning_effort"],
            "auto_attached_skills": meta.get("auto_attached_skills", []),
            "depends_on": depends_on,
        })
    # group by dependency wave (supports chains; independent tasks share a wave)
    groups: list[list[str]] = []
    placed: set[str] = set()
    while len(placed) < len(subtasks):
        wave = [s["id"] for s in subtasks
                if s["id"] not in placed and all(d in placed for d in s["depends_on"])]
        if not wave:  # cycle guard: fall back to sequential remainder
            wave = [s["id"] for s in subtasks if s["id"] not in placed]
        groups.append(wave)
        placed.update(wave)
    return {"task": task_text, "subtasks": subtasks, "waves": groups,
            "parallel": len(groups) == 1 and len(subtasks) > 1}


def run_plan(
    task_text: str = "",
    subtasks: list[dict[str, Any]] | None = None,
    escalate_on_bias: bool = False,
    synthesize: bool = False,
    gateway_url: str | None = None,
    transport: Any = None,
    timeout: float = 300.0,
    skills_matcher: Any = None,
) -> dict[str, Any]:
    """Create and run sub-agents per plan. Explicit `subtasks` override auto-planning.

    Each item may set: id/task_text (required), agent_profile, depends_on."""
    plan = plan_task(task_text, skills_matcher) if subtasks is None else {"task": task_text, "subtasks": [], "waves": []}
    if subtasks is not None:
        norm = []
        for i, st in enumerate(subtasks, start=1):
            meta = classify_task(st["task_text"], skills_matcher=skills_matcher)
            norm.append({
                "id": str(st.get("id") or f"S{i}"),
                "task_text": st["task_text"],
                "agent_profile": st.get("agent_profile") or meta["agent_profile"],
                "depends_on": [str(d) for d in st.get("depends_on", [])],
            })
        plan["subtasks"] = norm
        placed, groups = set(), []
        while len(placed) < len(norm):
            wave = [s["id"] for s in norm
                    if s["id"] not in placed and all(d in placed for d in s["depends_on"])]
            if not wave:
                wave = [s["id"] for s in norm if s["id"] not in placed]
            groups.append(wave)
            placed.update(wave)
        plan["waves"] = groups

    results: dict[str, dict[str, Any]] = {}

    def _run_one(st: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        upstream = [results[d]["content"] for d in st.get("depends_on", []) if d in results]
        context = ""
        if upstream:
            context = "Upstream sub-agent results:\n\n" + "\n\n---\n\n".join(upstream)
        res = dispatch_subtask(
            agent_profile=st["agent_profile"],
            task_text=st["task_text"],
            context=context,
            task_id=st["id"],
            gateway_url=gateway_url,
            transport=transport,
            timeout=timeout,
            escalate_on_bias=escalate_on_bias,
        )
        return st["id"], res

    for wave in plan["waves"]:
        if len(wave) == 1:
            sid, res = _run_one(next(s for s in plan["subtasks"] if s["id"] == wave[0]))
            results[sid] = res
        else:
            wave_tasks = [next(s for s in plan["subtasks"] if s["id"] == sid) for sid in wave]
            with ThreadPoolExecutor(max_workers=min(4, len(wave))) as pool:
                for sid, res in pool.map(_run_one, wave_tasks):
                    results[sid] = res

    aggregate = "\n\n".join(
        f"### {sid} [{results[sid]['agent_profile']} | {results[sid]['selected_model']}]\n{results[sid]['content']}"
        for sid in sorted(results)
    )
    synthesis: dict[str, Any] | None = None
    if synthesize:
        synthesis = dispatch_subtask(
            agent_profile="coder",
            task_text=(f"把以下子任务结果合并为一份连贯的最终回答（保留各结果的 Tier 标签与证据层级）：\n\n{aggregate}"),
            task_id="synthesize",
            gateway_url=gateway_url,
            transport=transport,
            timeout=timeout,
        )

    return {
        "plan": plan,
        "results": results,
        "aggregate": aggregate,
        "synthesis": (synthesis or {}).get("content"),
        "bias_scan_summary": {sid: results[sid]["bias_scan"]["verdict"] for sid in results},
    }
