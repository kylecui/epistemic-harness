"""Deterministic Epistemic Namespace & Weakest-Link Provenance DAG Engine.

Core hard constraints enforced in code (cannot be bypassed by LLM prompt drift):
1. Read-Only L1 Enforcement (fixes F-04 L1 Creep):
   Every L1/L2/L3 source_id referenced by an L5 claim MUST exist in the
   loaded knowledge stores. Inventing fake L1 axioms raises a hard error.
2. Transitive Weakest-Link Confidence Cap (fixes F-01):
   effective_tier = weakest(upstream_tiers) across the entire DAG (L1 > L2 > L3).
   Even if the model claims L1, code forcibly overrides it to L3 if any ancestor
   depends on an L3 heuristic.
3. Human Promotion Gate:
   L3/L5 items can NEVER mutate knowledge/l1_axioms/ directly; they are queued
   into promotions/pending_pr.yaml for explicit human approval.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

Tier = Literal["L1", "L2", "L3", "L4", "L5"]
# Lower rank = weaker epistemic strength (used for min() weakest-link calculation)
TIER_STRENGTH: dict[str, int] = {"L1": 3, "L2": 2, "L3": 1}
STRENGTH_TO_TIER: dict[int, str] = {3: "L1", 2: "L2", 1: "L3"}


class L5ClaimInput(BaseModel):
    claim_id: str = Field(..., min_length=2, description="Unique ID for this interim claim, e.g. L5-001")
    claim: str = Field(..., min_length=5, description="The interim derivation or conclusion text")
    claimed_tier: Literal["L1", "L2", "L3"] = Field(
        ..., description="Confidence ceiling the model believes this claim has"
    )
    source_ids: list[str] = Field(
        ..., min_length=1, description="Exact IDs from L1/L2/L3 stores, registered L4 inputs, or prior L5 claims"
    )
    assumptions: list[str] = Field(default_factory=list)
    conflicts_with_l1: list[str] = Field(default_factory=list)


class L5ClaimRecord(BaseModel):
    claim_id: str
    claim: str
    claimed_tier: str
    effective_tier: str
    downgraded: bool
    downgrade_reason: str | None = None
    source_ids: list[str]
    resolved_ancestor_tiers: dict[str, str]
    assumptions: list[str]
    conflicts_with_l1: list[str]
    status: Literal["provisional", "blocked_l1_conflict"] = "provisional"


class EpistemicEngine:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.knowledge_dir = repo_root / "knowledge"
        self.promotions_dir = repo_root / "promotions"
        self.l1_axioms: dict[str, dict[str, Any]] = {}
        self.l2_evidence: dict[str, dict[str, Any]] = {}
        self.l3_heuristics: dict[str, dict[str, Any]] = {}
        self.l4_inputs: dict[str, dict[str, Any]] = {}
        self.l5_claims: dict[str, L5ClaimRecord] = {}
        self._load_stores()

    def _load_stores(self) -> None:
        l1_path = self.knowledge_dir / "l1_axioms" / "axioms.yaml"
        l2_path = self.knowledge_dir / "l2_library" / "evidence.yaml"
        l3_path = self.knowledge_dir / "l3_heuristics" / "heuristics.yaml"

        if l1_path.exists():
            data = yaml.safe_load(l1_path.read_text(encoding="utf-8")) or {}
            for item in data.get("axioms", []):
                self.l1_axioms[item["id"]] = {**item, "tier": "L1", "read_only": True}

        if l2_path.exists():
            data = yaml.safe_load(l2_path.read_text(encoding="utf-8")) or {}
            for item in data.get("evidence", []):
                self.l2_evidence[item["id"]] = {**item, "tier": "L2"}

        if l3_path.exists():
            data = yaml.safe_load(l3_path.read_text(encoding="utf-8")) or {}
            for item in data.get("heuristics", []):
                # Enforce mandatory scope + counter_examples on every L3 item
                if not item.get("scope_conditions") or not item.get("counter_examples"):
                    raise ValueError(
                        f"L3 heuristic {item.get('id')} violates harness.yaml: "
                        "scope_conditions and counter_examples are mandatory."
                    )
                self.l3_heuristics[item["id"]] = {**item, "tier": "L3", "falsifiable": True}

    def _match(self, item: dict[str, Any], query: str) -> bool:
        if not query.strip():
            return True
        haystack = " ".join(str(v) for v in item.values()).lower()
        return any(tok in haystack for tok in query.lower().split())

    def query_l1(self, query: str = "") -> dict[str, Any]:
        matches = [v for v in self.l1_axioms.values() if self._match(v, query)]
        return {
            "epistemic_tier": "L1",
            "read_only": True,
            "policy": "ONLY cite returned L1 IDs. Do NOT invent new L1 axioms.",
            "items": matches,
        }

    def search_l2(self, query: str = "") -> dict[str, Any]:
        matches = [v for v in self.l2_evidence.values() if self._match(v, query)]
        return {
            "epistemic_tier": "L2",
            "policy": "L2 proves observed facts only; always preserve source and verified_at.",
            "items": matches,
        }

    def recall_l3(self, query: str = "") -> dict[str, Any]:
        matches = [v for v in self.l3_heuristics.values() if self._match(v, query)]
        return {
            "epistemic_tier": "L3",
            "falsifiable": True,
            "policy": (
                "MANDATORY: Treat as candidate hypothesis only. "
                "Any L5 conclusion referencing these IDs is hard-capped at L3."
            ),
            "items": matches,
        }

    def register_l4_input(self, input_id: str, statement: str, kind: str = "constraint") -> dict[str, Any]:
        if not input_id.startswith("L4-"):
            raise ValueError("L4 input_id must start with 'L4-'.")
        record = {"id": input_id, "tier": "L4", "kind": kind, "statement": statement}
        self.l4_inputs[input_id] = record
        return {"registered": record, "note": "L4 directs optimization goals but cannot override L1."}

    def _resolve_source_strength(self, source_id: str) -> tuple[str, int | None]:
        """Return (resolved_tier_label, strength_score_or_None_for_L4)."""
        if source_id in self.l1_axioms:
            return ("L1", TIER_STRENGTH["L1"])
        if source_id in self.l2_evidence:
            return ("L2", TIER_STRENGTH["L2"])
        if source_id in self.l3_heuristics:
            return ("L3", TIER_STRENGTH["L3"])
        if source_id in self.l4_inputs:
            # L4 is user intent/constraint; it does not raise or lower objective epistemic truth tier by itself
            return ("L4", None)
        if source_id in self.l5_claims:
            prior = self.l5_claims[source_id]
            return (f"L5(capped:{prior.effective_tier})", TIER_STRENGTH[prior.effective_tier])
        if source_id.startswith("L1-"):
            raise ValueError(
                f"L1_CREEP_BLOCKED: '{source_id}' does not exist in read-only l1_axioms/. "
                "Models cannot invent L1 axioms; classify as L3 heuristic or L4 constraint instead."
            )
        raise ValueError(
            f"UNKNOWN_SOURCE_ID: '{source_id}' not found in L1/L2/L3 stores or session L4/L5 registry."
        )

    def submit_l5_claim(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = L5ClaimInput(**payload)
        resolved: dict[str, str] = {}
        strengths: list[int] = []

        for sid in data.source_ids:
            tier_label, score = self._resolve_source_strength(sid)
            resolved[sid] = tier_label
            if score is not None:
                strengths.append(score)

        # Verify conflicts_with_l1 IDs exist in L1 store
        for l1_id in data.conflicts_with_l1:
            if l1_id not in self.l1_axioms:
                raise ValueError(f"UNKNOWN_L1_CONFLICT_ID: '{l1_id}' is not in l1_axioms/.")

        # If a claim ONLY cites L4 user inputs with zero L1/L2/L3 grounding, cap at L3 (unverified assumption)
        weakest_strength = min(strengths) if strengths else TIER_STRENGTH["L3"]
        effective_tier = STRENGTH_TO_TIER[weakest_strength]

        downgraded = TIER_STRENGTH[data.claimed_tier] > weakest_strength
        downgrade_reason = None
        if downgraded:
            downgrade_reason = (
                f"WEAKEST_LINK_OVERRIDE: Model claimed {data.claimed_tier}, "
                f"but upstream dependencies {resolved} hard-cap this claim at {effective_tier}."
            )

        status: Literal["provisional", "blocked_l1_conflict"] = (
            "blocked_l1_conflict" if data.conflicts_with_l1 else "provisional"
        )

        record = L5ClaimRecord(
            claim_id=data.claim_id,
            claim=data.claim,
            claimed_tier=data.claimed_tier,
            effective_tier=effective_tier,
            downgraded=downgraded,
            downgrade_reason=downgrade_reason,
            source_ids=data.source_ids,
            resolved_ancestor_tiers=resolved,
            assumptions=data.assumptions,
            conflicts_with_l1=data.conflicts_with_l1,
            status=status,
        )
        self.l5_claims[record.claim_id] = record
        return record.model_dump() if hasattr(record, 'model_dump') else record.dict()

    def audit_dag(self) -> dict[str, Any]:
        blocked = [c.claim_id for c in self.l5_claims.values() if c.status == "blocked_l1_conflict"]
        downgraded = [c.claim_id for c in self.l5_claims.values() if c.downgraded]
        if not self.l5_claims:
            overall_cap = "NONE"
        else:
            min_score = min(TIER_STRENGTH[c.effective_tier] for c in self.l5_claims.values())
            overall_cap = STRENGTH_TO_TIER[min_score]

        return {
            "total_l5_claims": len(self.l5_claims),
            "overall_confidence_cap": overall_cap,
            "converge_allowed": len(blocked) == 0,
            "blocked_l1_conflicts": blocked,
            "downgraded_claims": downgraded,
            "claims": [c.model_dump() if hasattr(c, 'model_dump') else c.dict() for c in self.l5_claims.values()],
        }

    def propose_promotion(
        self, source_id: str, target_tier: Literal["L1", "L2"], rationale: str
    ) -> dict[str, Any]:
        # Validate source exists
        self._resolve_source_strength(source_id)
        self.promotions_dir.mkdir(parents=True, exist_ok=True)
        pr_file = self.promotions_dir / "pending_pr.yaml"
        existing = yaml.safe_load(pr_file.read_text(encoding="utf-8")) if pr_file.exists() else {}
        queue: list[dict[str, Any]] = (existing or {}).get("pending_promotions", [])

        pr_entry = {
            "pr_id": f"PR-{len(queue) + 1:03d}",
            "source_id": source_id,
            "target_tier": target_tier,
            "rationale": rationale,
            "status": "awaiting_human_approval",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        queue.append(pr_entry)
        pr_file.write_text(
            yaml.safe_dump({"pending_promotions": queue}, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return {
            "queued": pr_entry,
            "message": "Direct writes to L1/L2 are forbidden. Queued in promotions/pending_pr.yaml for human PR review.",
        }
