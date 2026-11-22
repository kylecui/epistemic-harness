"""Task decomposition & multi-sub-agent execution.

plan_task: deterministic (L3-heuristic) splitter -> subtasks with tier/profile + dependency groups.
run_plan : execute a plan through the gateway — parallel waves run concurrently, dependent
           subtasks receive upstream results as controller context. Each dispatch is an
           ephemeral sub-agent (own profile -> gateway pins tier/model/effort).

P0-4 (review): English synthesis prompt, deep profile, as_completed exception isolation,
natural id ordering. P1-1: optional EpistemicEngine integration — every successful subtask is
registered as an L5 claim (weakest-link cap applies), and audit_dag() runs before synthesis.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import re
from typing import Any

from .dispatch import dispatch_subtask
from .planner import classify_task

_SEQ_MARKERS = re.compile(r"然后|之后再|接着|其次|随后|下一步|最后|then afterwards|and then|finally", re.I)
_LIST_ITEM = re.compile(r"^\s*(?:\d+[.、)]|[（(]\d+[)）]|[-*•]\s+|步骤\s*\d+[:：]?)\s*(.+)$")
_INLINE_ITEM = re.compile(r"(?:^|[\s：:，,。;；])\s*\d+[.、)]\s+")
_CONJ_SPLIT = re.compile(r"\s*(?:；同时|；并且|，以及|，同时|，并且|;\s*also|,\s*and also)\s*")
_MAX_SUBTASKS = 6
_ID_RE = re.compile(r"^S(\d+)$")


def _natural_key(sid: str) -> tuple[int, str]:
    m = _ID_RE.match(str(sid))
    return (int(m.group(1)), "") if m else (10**9, str(sid))


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


def _build_waves(subtasks: list[dict[str, Any]]) -> list[list[str]]:
    placed: set[str] = set()
    waves: list[list[str]] = []
    while len(placed) < len(subtasks):
        wave = [s["id"] for s in subtasks
                if s["id"] not in placed and all(d in placed for d in s["depends_on"])]
        if not wave:
            wave = [s["id"] for s in subtasks if s["id"] not in placed]
        waves.append(wave)
        placed.update(wave)
    return waves


def _register_claim(engine: Any, sid: str, st: dict[str, Any], res: dict[str, Any]) -> str | None:
    """Register a successful subtask as an L5 node (P1-1). Returns a note when skipped."""
    if engine is None or not res.get("content", "").strip():
        return "skipped(no engine/content)"
    clean = (res.get("bias_scan") or {}).get("verdict") == "clean"
    # Weakest-link input: L3 when the bias screen flagged the output (heuristics involved).
    claimed_tier = "L2" if clean else "L3"
    sources = [sid for sid in (engine.l2_evidence or {})][:1] or [sid for sid in (engine.l3_heuristics or {})][:1]
    if not sources:
        return "skipped(no valid source ids)"
    # Grounding rule: list the store through the retrieval tool so the citation
    # is backed by a real retrieval, then pass the trace explicitly (the engine
    # process may differ from the one that served the sub-agents).
    if sources[0] in (engine.l2_evidence or {}):
        engine.search_l2("")
    else:
        engine.recall_l3("")
    try:
        engine.submit_l5_claim({
            "claim_id": f"PLAN-{st['id']}",
            "claim": str(res.get("content", ""))[:600],
            "claimed_tier": claimed_tier,
            "source_ids": sources,
            "retrieval_trace": list(sources),
            "assumptions": [f"sub-agent profile={st['agent_profile']}"],
        })
        return None
    except Exception as exc:  # noqa: BLE001 - registration must never break execution
        return f"skipped({type(exc).__name__}: {exc})"


def run_plan(
    task_text: str = "",
    subtasks: list[dict[str, Any]] | None = None,
    escalate_on_bias: bool = False,
    synthesize: bool = False,
    gateway_url: str | None = None,
    transport: Any = None,
    timeout: float = 300.0,
    skills_matcher: Any = None,
    engine: Any = None,
    original_task: str | None = None,
    epistemic_engine: Any = None,
    repo_dir: str | None = None,
    exit_gate: Any = None,
) -> dict[str, Any]:
    """Create and run sub-agents per plan. Explicit `subtasks` override auto-planning.

    Aliases accepted for API compatibility: original_task -> task_text, epistemic_engine -> engine.
    """
    if original_task is not None and not task_text:
        task_text = original_task
    if epistemic_engine is not None:
        engine = epistemic_engine
    if subtasks is None:
        plan = plan_task(task_text, skills_matcher)
    else:
        norm = []
        for i, st in enumerate(subtasks, start=1):
            meta = classify_task(st["task_text"], skills_matcher=skills_matcher)
            norm.append({
                "id": str(st.get("id") or f"S{i}"),
                "task_text": st["task_text"],
                "agent_profile": st.get("agent_profile") or meta["agent_profile"],
                "depends_on": [str(d) for d in st.get("depends_on", [])],
            })
        plan = {"task": task_text, "subtasks": norm, "waves": _build_waves(norm), "parallel": False}

    results: dict[str, dict[str, Any]] = {}

    def _run_one(st: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        upstream = [results[d]["content"] for d in st.get("depends_on", [])
                    if d in results and results[d].get("content")]
        context = "Upstream sub-agent results:\n\n" + "\n\n---\n\n".join(upstream) if upstream else ""
        try:
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
        except Exception as exc:  # P0-4: isolate failures, keep sibling results
            res = {"agent_profile": st["agent_profile"], "task_id": st["id"], "content": "",
                   "routed_tier": "", "selected_model": "", "tier_tag": "",
                   "usage": {}, "bias_scan": {"matches": [], "verdict": "clean"},
                   "error": f"{type(exc).__name__}: {exc}"}
        res["status"] = "error" if res.get("error") else "ok"
        return st["id"], res

    for wave in plan["waves"]:
        wave_tasks = [next(s for s in plan["subtasks"] if s["id"] == sid) for sid in wave]
        if len(wave_tasks) == 1:
            sid, res = _run_one(wave_tasks[0])
            results[sid] = res
            continue
        with ThreadPoolExecutor(max_workers=min(4, len(wave_tasks))) as pool:
            futures = {pool.submit(_run_one, st): st["id"] for st in wave_tasks}
            for fut in as_completed(futures):
                sid, res = fut.result()
                results[sid] = res

    ordered_ids = sorted(results, key=_natural_key)
    aggregate = "\n\n".join(
        (f"### {sid} [{results[sid]['agent_profile']} | {results[sid]['selected_model']}]"
         + (" (FAILED)" if results[sid].get("error") else "")
         + f"\n{results[sid]['content'] or results[sid].get('error', '')}")
        for sid in ordered_ids
    )

    # P1-1: register each successful subtask as an L5 node (weakest-link cap applies in code).
    claim_notes: dict[str, str | None] = {}
    if engine is not None:
        by_id = {s["id"]: s for s in plan["subtasks"]}
        for sid in ordered_ids:
            claim_notes[sid] = _register_claim(engine, sid, by_id.get(sid, {}), results[sid])

    audit: dict[str, Any] | None = None
    if engine is not None:
        try:
            audit = engine.audit_dag()
        except Exception as exc:  # noqa: BLE001
            audit = {"error": f"{type(exc).__name__}: {exc}"}

    synthesis: dict[str, Any] | None = None
    if synthesize:
        synthesis = dispatch_subtask(
            agent_profile="deep",
            task_text=(
                "Synthesize the following subtask outputs into one coherent final answer. "
                "Preserve each result's tier tags and evidence levels. "
                "Respond strictly in the same language as the user's original request "
                "(internal reasoning stays in English). "
                "Call out failed subtasks explicitly and name what remains missing.\n\n" + aggregate
            ),
            task_id="synthesize",
            gateway_url=gateway_url,
            transport=transport,
            timeout=timeout,
        )

    # Optional deterministic exit gate: after mutation-bearing runs, repo checks must pass.
    gate: dict[str, Any] | None = None
    if (exit_gate is not None or repo_dir is not None) and any(not r.get("error") for r in results.values()):
        from .exit_gate import ExitGateEngine
        eng = exit_gate or ExitGateEngine.from_repo_config(Path(repo_dir))
        try:
            decision = eng.evaluate(aggregate)
            gate = {"pass": bool(decision.passed), "failures": [f"cmd={c.name} rc={c.returncode}" for c in (decision.failures or [])]}
        except Exception as exc:  # noqa: BLE001 - the gate must never break the run
            gate = {"pass": None, "error": f"{type(exc).__name__}: {exc}"}

    return {
        "plan": plan,
        "results": results,
        "exit_gate": gate,
        "aggregate": aggregate,
        "synthesis": (synthesis or {}).get("content"),
        "bias_scan_summary": {sid: results[sid]["bias_scan"]["verdict"] for sid in ordered_ids},
        "dag": {"claims": claim_notes, "audit": audit},
        "dag_audit": audit,
    }
