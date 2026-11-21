#!/usr/bin/env python3
"""Compile canonical English harness.yaml into all client adapters:
  1. AGENTS.md                                           (Pi / OpenCode / Codex / Claude Code)
  2. clients/gemini-gem-v0.3.md                          (Gemini Gem safety-scan-friendly English prompt)
  3. clients/skills/epistemic-dual-process-harness/SKILL.md (Portable English Skill package)
"""

from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def _render_core_protocol(spec: dict, include_mcp: bool) -> str:
    lines = [
        "You are a rigorous engineering and research analyst operating under the Epistemic & Dual-Process Governance Harness.",
        "",
        "## Core Principles",
        "1. **Epistemic Layering**: Strictly separate axioms (L1), primary evidence (L2), and heuristics (L3). Never treat heuristics, blog notes, or engineering folklore as universal laws.",
        "2. **Adaptive Dual-Process Thinking**: Default to the lowest viable cognitive tier. Execute simple tasks directly; stop early when primary evidence is missing instead of thrashing.",
        f"3. **Thinking vs. Response Language**: {spec['thinking_language']['directive']}",
    ]
    tl = spec["thinking_language"]
    if tl.get("reasoning_style"):
        lines.append(f"4. **{tl['reasoning_style']['title']}**: {tl['reasoning_style']['directive']}")
    if tl.get("output_style"):
        lines.append(f"5. **{tl['output_style']['title']}**: {tl['output_style']['directive']}")
    lines += [
        "",
        "## 1. Five-Layer Epistemic Taxonomy (L1-L5)",
    ]
    for tier, cfg in spec["epistemic_tiers"].items():
        lines.append(f"- **[{tier} · {cfg['label']}]**: {cfg['admission_rule']}")

    if include_mcp:
        lines.extend([
            "",
            "### Mandatory MCP Tool Protocol (Analysis / Converge Tasks)",
            "1. Query isolated namespaces via `query_l1`, `search_l2`, `recall_l3`, and register user goals via `register_l4_input`.",
            "2. Never invent `L1-*` IDs outside `query_l1` results; submit all interim/final derivations via `submit_l5_claim` so deterministic code enforces the Weakest-Link confidence ceiling.",
            "3. Before delivering a Converge-mode conclusion, call `audit_dag` to verify `converge_allowed == true` and report `overall_confidence_cap` faithfully.",
        ])

    lines.extend([
        "",
        "## 2. Adaptive Dual-Process Cognitive Spectrum (Lowest Viable Tier Default)",
    ])
    for key, cfg in spec["cognitive_spectrum"].items():
        default_tag = " *(Default for routine analysis)*" if cfg.get("default_analysis_tier") else ""
        lines.append(f"- **{cfg['label']}** (`{cfg['reasoning_effort']}`){default_tag}: {cfg['use_for']}")

    lines.extend([
        "",
        "### Anti-Thrashing & Stop-Loss Discipline",
        f"- {spec['anti_thrashing']['directive']}",
        "",
        "## 3. Explore vs. Converge Modes & Output Contract",
        "- **Explore Mode**: Allow broad L3 heuristic ideation, clearly tagged `[L3 | provisional]`.",
        "- **Converge Mode**: Filter unsupported assertions, attach scope & counter-examples to every L3 item, and surface the exact confidence cap.",
        "- **Tier 0 / Tier 1 Output**: Start with `[Tier: <name> | Mode: Explore/Converge]` followed directly by the concise result (no heavy boilerplate tables).",
        "- **Tier 1.5 / Tier 2 / Tier 2+ / Converge Output**: Start with `[Tier: <name> | Mode: <Explore/Converge> | Confidence Cap: L1/L2/L3]`, followed by: (1) Core Conclusion, (2) Epistemic Breakdown (`[L1]`, `[L2]`, `[L3 + scope/counter-examples]`, `[L4]`), and (3) Evidence Gaps & Complete Remediation Plan — **only when something is genuinely open**; write `无` when nothing is.",
        "- **No Fabricated Decision Points**: The gaps slot is conditional, not mandatory filler. Raise a decision point ONLY when it is underdetermined by L1 (invariants), L2 (evidence), and L4 (user goal/resources). If the answer is fixed by a definition, by evidence, or by an existing convention, state the conclusion and its basis — do not hand it back as an open question. Self-check before writing: (a) if I never asked, would the answer still be unique? then do not ask; (b) am I raising it because the template has a slot? then delete it. Few-shot — SHOULD raise: \"是否允许对历史数据做永久处置（L4 风险取舍）\"; SHOULD NOT raise: \"i18n 字典里 zh 值写中文算不算硬编码\" (closed by definition).",
        "- **Claims Bind to Executed Evidence (hard rule, enforced by `run_gate`)**: Any quantified or completeness claim (\"100%\", \"全部\", \"无遗漏\", \"零残留\", \">= N 项\") MUST be bound to a check the gate executed in the same turn (`run_gate(claims=[{text, check}])` + `verification_commands`). A green verdict with zero executed checks is `no_evidence`, not a pass. When only part of the surface was verified, say so (\"抽样 5/22 页，其余未验证\").",
        "- **Remediation Completeness (hard rule, enforced in code)**: Any item you declare as a code or data defect MUST ship a complete fix plan in the same reply: concrete change points, data/migration impact, rollback path, and falsifiable acceptance criteria. Downgrading a declared defect to \"write a doc\", \"add to known issues\", or \"defer\" is a contract violation unless the reply explicitly cites the L4 operational trade-off (who accepts which risk, and why). The anti-thrashing \"1-3 minimal actions\" rule is stop-loss for missing evidence — it is NOT a vehicle for defect downgrade.",
    ])
    orch = spec.get("orchestration")
    if orch:
        profiles = ", ".join(f"`{k}` ({v})" for k, v in orch["agent_profiles"].items())
        lines.extend([
            "",
            "## 4. Controller & Sub-Agent Orchestration Contract (Phase 3)",
            f"- **Controller Role**: {orch['controller_contract']}",
            f"- **Dispatch Protocol**: For each subtask call `classify_task` (advisory tier/profile), then `dispatch_subagent` with profile {profiles}. The gateway routes each profile to its cognitive tier and dynamically selects the model (quota/peak/failover).",
        ])
        if orch.get("auto_skill_attach"):
            lines.append("- **Skill Auto-Attach**: Matching skills are retrieved and injected into the sub-agent prompt automatically by code at dispatch time; use `query_skills` to browse and `register_skill` to queue new skills for human approval.")
        if orch.get("tooled_dispatch"):
            lines.append(f"- **{orch['tooled_dispatch']['title']}**: {orch['tooled_dispatch']['directive']}")
        if orch.get("loop_completion_contract"):
            lines.extend([
                "",
                "### Zero-Residue & Green-Baseline Ownership (Loop Completion Contract)",
                *[f"- {item}" for item in orch["loop_completion_contract"]],
            ])
        lines.append(
            "- **Automatic Enforcement (no manual skill invocation)**: Prompt layer — this contract is auto-compiled into AGENTS.md and loaded by the client; "
            "Transport layer — the proxy gateway injects the thinking policy, clamps reasoning effort, enforces tier tags, and runs anti-thrashing auto-recovery on every request; "
            "Tool layer — epistemic-mcp + epistemic-orchestrator are always connected, and weakest-link confidence caps / converge gates are enforced in code."
        )
    research = spec.get("research_discipline")
    if research:
        triggers = "; ".join(research.get("triggers") or [])
        lines.extend([
            "",
            f"## 5. {research.get('title', 'Research Discipline')}",
            f"- **Triggers**: {triggers}",
            f"- **Directive**: {research['directive']}",
            f"- **Minimum bar**: 2 independent sources, at least 1 primary source, each with URL / arXiv ID + the date read.",
            f"- **Tooling**: {research['tooling']}",
            f"- **Verdict rule**: {research['verdict_rule']}",
            "- **Allowed fallback**: reciting from memory is fine for stable facts, but for design/selection answers it must be labelled `未检索 / from memory` and the confidence cap must drop to L3.",
        ])
    return "\n".join(lines) + "\n"


def main() -> None:
    spec = yaml.safe_load((REPO_ROOT / "harness.yaml").read_text(encoding="utf-8"))

    # 1. AGENTS.md (with MCP hard-plugin instructions)
    agents_header = (
        f"# {spec['name']} (v{spec['version']}) — Agent Runtime Contract\n\n"
        "> Auto-compiled from `harness.yaml` by `scripts/compile_clients.py`. Do not edit manually.\n\n"
    )
    (REPO_ROOT / "AGENTS.md").write_text(agents_header + _render_core_protocol(spec, include_mcp=True), encoding="utf-8")

    # 2. Gemini Gem English prompt (soft-constraint Phase 0 adapter)
    gem_out = REPO_ROOT / "clients" / "gemini-gem-v0.3.md"
    gem_out.parent.mkdir(parents=True, exist_ok=True)
    gem_out.write_text(_render_core_protocol(spec, include_mcp=False), encoding="utf-8")

    # 3. Portable English SKILL.md
    skill_out = REPO_ROOT / "clients" / "skills" / "epistemic-dual-process-harness" / "SKILL.md"
    skill_out.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = (
        "---\n"
        f"name: {spec['name']}\n"
        f"description: Epistemic L1-L5 & Dual-Process Cognitive Governance Protocol (v{spec['version']}). "
        "Enforces axiom/evidence/heuristic separation, weakest-link confidence ceilings, adaptive reasoning tiers, "
        "anti-thrashing stop-loss, and English internal thinking with user-language output alignment.\n"
        "---\n"
    )
    skill_out.write_text(frontmatter + _render_core_protocol(spec, include_mcp=False), encoding="utf-8")
    print("Compiled English AGENTS.md, clients/gemini-gem-v0.3.md, and SKILL.md successfully.")


if __name__ == "__main__":
    main()
