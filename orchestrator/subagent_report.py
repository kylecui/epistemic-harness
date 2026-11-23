"""SubagentReport: wrap free-text dispatch results into schema-validated interim outputs.

Research branch: structured-interim-contracts (Paper 2, P1). The controller
currently receives sub-agent results as prose and re-parses them at converge
time; this module is the first protocol-layer step: keep the raw text, but
also emit a SubagentReport whose findings carry explicit epistemic layers, so
the parent can converge by id lookup instead of re-reading prose.

Wiring note (P1.5): attach at the MCP server boundary (orchestrator/server.py)
as an additive field/tool so existing consumers of dispatch_subagent are
unaffected.
"""

from __future__ import annotations

from typing import Any

from proxy_gateway.interim_schema import load_schema, validate

SCHEMA_NAME = "subagent-report.schema.json"
_VALID_PROFILES = ("explorer", "explorer-ro", "coder", "deep", "critic")


def build_report(task_id: str, profile: str, raw_text: str, evidence: list[dict] | None = None) -> dict[str, Any]:
    """Project a free-text sub-agent result into a SubagentReport.

    Findings are split on blank lines and marked layer L3 (heuristic): raw
    sub-agent prose has no machine-verifiable provenance, so the weakest
    honest layer is the correct default — a parent may promote a finding to
    L2 only after binding it to executed evidence itself.
    """
    paragraphs = [p.strip() for p in (raw_text or "").split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = ["(empty sub-agent result)"]
    findings = [
        {"id": f"F{i + 1}", "text": p[:2000], "layer": "L3"}
        for i, p in enumerate(paragraphs)
    ]
    return {
        "schema": "subagent-report/v1",
        "task_id": task_id,
        "profile": profile if profile in _VALID_PROFILES else "explorer",
        "findings": findings,
        "evidence": evidence or [],
        "confidence_cap": "L3",
        "gaps": [],
        "recommendation": "",
        "residue_risks": [],
    }


def validate_report(report: dict[str, Any]) -> list[str]:
    return validate(load_schema(SCHEMA_NAME), report)
