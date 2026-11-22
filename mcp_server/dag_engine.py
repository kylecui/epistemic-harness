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
import json
import os
from pathlib import Path
import re
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

Tier = Literal["L1", "L2", "L3", "L4", "L5"]
# Lower rank = weaker epistemic strength (used for min() weakest-link calculation)
TIER_STRENGTH: dict[str, int] = {"L1": 3, "L2": 2, "L3": 1}
STRENGTH_TO_TIER: dict[int, str] = {3: "L1", 2: "L2", 1: "L3"}

# CJK bigram + ascii-word tokenizer for implicit-dependency detection.
# Deliberately local (not imported from memory_index): this module must stay
# importable standalone for tests and compile_clients.
_CJK_RUN = re.compile(r"[\u3400-\u9fff]+")
_ASCII_WORD = re.compile(r"[a-z0-9_\-]{2,}")


def _text_tokens(text: str) -> set[str]:
    low = (text or "").lower()
    toks: set[str] = set(_ASCII_WORD.findall(low))
    for run in _CJK_RUN.findall(low):
        toks.update(run[i:i + 2] for i in range(len(run) - 1))
        if len(run) <= 6:
            toks.add(run)
    return {t for t in toks if t.strip()}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def _containment(a: set[str], b: set[str]) -> float:
    """Fraction of b's tokens covered by a. Paraphrases keep the source's
    content words even when they add many of their own, so Jaccard alone
    under-fires on loose paraphrases; containment catches them."""
    return len(a & b) / len(b) if b else 0.0


class L5ClaimInput(BaseModel):
    claim_id: str = Field(..., min_length=2, description="Unique ID for this interim claim, e.g. L5-001")
    claim: str = Field(..., min_length=5, description="The interim derivation or conclusion text")
    claimed_tier: Literal["L1", "L2", "L3"] = Field(
        ..., description="Confidence ceiling the model believes this claim has"
    )
    source_ids: list[str] = Field(
        ..., min_length=1, description="Exact IDs from L1/L2/L3 stores, registered L4 inputs, or prior L5 claims"
    )
    retrieval_trace: list[str] = Field(
        default_factory=list,
        description=(
            "IDs this session actually retrieved via query_l1/search_l2/recall_l3 "
            "(the engine also tracks them automatically). Grounding rule: every cited "
            "L1/L2/L3 source must appear in the retrieval trace or the engine session log."
        ),
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
    # L3 heuristics whose text matches the claim but were NOT cited by the model;
    # detected in code and force-inherited as dependencies (anti-laundering).
    implicit_dependencies: list[str] = Field(default_factory=list)
    status: Literal["provisional", "blocked_l1_conflict"] = "provisional"


class EpistemicEngine:
    def __init__(self, repo_root: Path, store_root: Path | None = None, *, implicit_l3_threshold: float = 0.35, implicit_l3_containment_threshold: float = 0.15) -> None:
        self.repo_root = repo_root
        self.knowledge_dir = repo_root / "knowledge"
        self.promotions_dir = repo_root / "promotions"
        # Persisted memory may live elsewhere (tests / CI must not write into the
        # real store). HARNESS_MEMORY_STORE keeps that redirect scriptable.
        self.store_root = Path(store_root or os.environ.get("HARNESS_MEMORY_STORE") or repo_root)
        self.l5_store_dir = self.store_root / "knowledge" / "l5_store"
        self.l4_store_path = self.store_root / ".pi" / "l4_inputs.jsonl"
        self.l1_axioms: dict[str, dict[str, Any]] = {}
        self.l2_evidence: dict[str, dict[str, Any]] = {}
        self.l3_heuristics: dict[str, dict[str, Any]] = {}
        self.l4_inputs: dict[str, dict[str, Any]] = {}
        self.l5_claims: dict[str, L5ClaimRecord] = {}
        self.l5_claims: dict[str, L5ClaimRecord] = {}
        # Anti-laundering (2026-11-22 review, defect #1):
        #  * session_retrieved_ids: every L1/L2/L3 id the tools actually returned
        #    in this process. A claim may only cite what was retrieved — citing
        #    an id the model never saw means the citation was fabricated from
        #    context/memory rather than grounded in the stores.
        #  * implicit detection: claims whose text matches an L3 heuristic but
        #    do not cite it get that heuristic force-added as a dependency, so
        #    "blogs say X" cannot be laundered into an L1/L2-capped conclusion.
        self.session_retrieved_ids: set[str] = set()
        # Combined similarity gate, calibrated on
        # tests/test_l5_grounding_adversarial.py (2026-11-22):
        #   jaccard(title|claim)  — attacks >= 0.28 near-copies, clean <= 0.05
        #   containment(claim)    — loose paraphrases 0.19-0.69, clean <= 0.10
        self.implicit_l3_threshold: float = implicit_l3_threshold
        self.implicit_l3_containment_threshold: float = implicit_l3_containment_threshold
        # Claims created in THIS process; audit_dag defaults to the session view so
        # a long-lived store never silently changes a fresh session's converge gate.
        self.session_claim_ids: set[str] = set()
        self._load_stores()
        self._load_persisted_l4_l5()

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

    def _persist_l4(self, record: dict[str, Any]) -> None:
        """L4 user intent must survive a restart; it is the anchor every audit cites."""
        try:
            self.l4_store_path.parent.mkdir(parents=True, exist_ok=True)
            with self.l4_store_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass  # persistence is best-effort; never break the tool call

    def _persist_l5(self, record: L5ClaimRecord) -> None:
        """Append-only monthly L5 store: the derivation memory that used to die with the process."""
        try:
            self.l5_store_dir.mkdir(parents=True, exist_ok=True)
            month = datetime.now(timezone.utc).strftime("%Y-%m")
            payload = {
                **record.model_dump(),
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            with (self.l5_store_dir / f"{month}.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _load_persisted_l4_l5(self) -> None:
        """Hydrate L4 inputs + prior L5 derivations so reuse inherits the same cap."""
        if self.l4_store_path.exists():
            for raw in self.l4_store_path.read_text(encoding="utf-8").splitlines():
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if rec.get("id"):
                    self.l4_inputs[rec["id"]] = rec
        if not self.l5_store_dir.exists():
            return
        for path in sorted(self.l5_store_dir.glob("*.jsonl")):
            for raw in path.read_text(encoding="utf-8").splitlines():
                try:
                    rec = L5ClaimRecord(**json.loads(raw))
                except Exception:  # malformed line must not take down the server
                    continue
                self.l5_claims.setdefault(rec.claim_id, rec)

    def _match(self, item: dict[str, Any], query: str) -> bool:
        if not query.strip():
            return True
        haystack = " ".join(str(v) for v in item.values()).lower()
        return any(tok in haystack for tok in query.lower().split())

    def query_l1(self, query: str = "") -> dict[str, Any]:
        matches = [v for v in self.l1_axioms.values() if self._match(v, query)]
        self.session_retrieved_ids.update(m["id"] for m in matches)
        return {
            "epistemic_tier": "L1",
            "read_only": True,
            "policy": "ONLY cite returned L1 IDs. Do NOT invent new L1 axioms.",
            "items": matches,
        }

    def search_l2(self, query: str = "") -> dict[str, Any]:
        matches = [v for v in self.l2_evidence.values() if self._match(v, query)]
        self.session_retrieved_ids.update(m["id"] for m in matches)
        return {
            "epistemic_tier": "L2",
            "policy": "L2 proves observed facts only; always preserve source and verified_at.",
            "items": matches,
        }

    def recall_l3(self, query: str = "") -> dict[str, Any]:
        matches = [v for v in self.l3_heuristics.values() if self._match(v, query)]
        self.session_retrieved_ids.update(m["id"] for m in matches)
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
        record = {"id": input_id, "tier": "L4", "kind": kind, "statement": statement,
                  "registered_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self.l4_inputs[input_id] = record
        self._persist_l4(record)
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

    def _detect_implicit_l3(self, claim_text: str, cited: set[str]) -> list[str]:
        """L3 heuristics whose text overlaps the claim but were not cited.

        Deterministic anti-laundering: a model may not reach an L1/L2-capped
        conclusion whose substance is a blog-style heuristic by simply omitting
        the heuristic from source_ids.
        """
        claim_tokens = _text_tokens(claim_text)
        if not claim_tokens:
            return []
        hits: list[tuple[str, float]] = []
        for hid, item in self.l3_heuristics.items():
            if hid in cited:
                continue
            claim_toks = _text_tokens(str(item.get("claim", "")))
            hit = (
                _jaccard(claim_tokens, _text_tokens(str(item.get("title", "")))) >= self.implicit_l3_threshold
                or _jaccard(claim_tokens, claim_toks) >= self.implicit_l3_threshold
                or _containment(claim_tokens, claim_toks) >= self.implicit_l3_containment_threshold
            )
            if hit:
                hits.append((hid, max(
                    _jaccard(claim_tokens, _text_tokens(str(item.get("title", "")))),
                    _jaccard(claim_tokens, claim_toks),
                    _containment(claim_tokens, claim_toks),
                )))
        hits.sort(key=lambda kv: -kv[1])
        return [hid for hid, _ in hits]

    def submit_l5_claim(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = L5ClaimInput(**payload)
        resolved: dict[str, str] = {}
        strengths: list[int] = []

        for sid in data.source_ids:
            tier_label, score = self._resolve_source_strength(sid)
            resolved[sid] = tier_label
            if score is not None:
                strengths.append(score)

        # --- Grounding rule (hard error) ------------------------------------
        # Every cited L1/L2/L3 source must have been returned by the retrieval
        # tools in this session (engine-tracked) or be declared in the caller's
        # retrieval_trace. Prior L5 claims are exempt (they were validated when
        # created); L4 user intent is exempt (registered, not retrieved).
        seen = self.session_retrieved_ids | set(data.retrieval_trace)
        ungrounded = [
            sid for sid in data.source_ids
            if resolved.get(sid, "").startswith(("L1", "L2", "L3")) and sid not in seen
        ]
        if ungrounded:
            raise ValueError(
                "GROUNDING_VIOLATION: cited sources were never retrieved this session: "
                f"{ungrounded}. Call query_l1/search_l2/recall_l3 (or pass retrieval_trace) "
                "before citing — a citation the tools never returned is not evidence."
            )

        # --- Implicit L3 dependency detection -------------------------------
        implicit = self._detect_implicit_l3(data.claim, set(data.source_ids))
        if implicit:
            for hid in implicit:
                resolved[hid] = "L3(implicit)"
            strengths.append(TIER_STRENGTH["L3"])

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
            parts = [
                f"WEAKEST_LINK_OVERRIDE: Model claimed {data.claimed_tier}, "
                f"but upstream dependencies {resolved} hard-cap this claim at {effective_tier}."
            ]
            if implicit:
                parts.append(
                    f"IMPLICIT_L3_DEPENDENCY: claim text matches uncited heuristics {implicit}; "
                    "they were force-inherited as dependencies."
                )
            downgrade_reason = " ".join(parts)

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
            implicit_dependencies=implicit,
            status=status,
        )
        self.l5_claims[record.claim_id] = record
        self.session_claim_ids.add(record.claim_id)
        self._persist_l5(record)
        return record.model_dump() if hasattr(record, 'model_dump') else record.dict()

    def query_l5(self, query: str = "", limit: int = 5) -> dict[str, Any]:
        """Recall prior derivations (persisted + session) so work is not re-derived."""
        items = [c for c in self.l5_claims.values() if self._match(c.model_dump(), query)]
        items.sort(key=lambda c: c.claim_id)
        return {
            "epistemic_tier": "L5",
            "policy": (
                "Reusing a prior claim inherits its effective_tier as a hard cap; "
                "cite the claim_id instead of re-deriving it."
            ),
            "total": len(items),
            "items": [c.model_dump() for c in items[:limit]],
        }

    def audit_dag(self, include_persisted: bool = False) -> dict[str, Any]:
        claims = [
            c for cid, c in self.l5_claims.items()
            if include_persisted or cid in self.session_claim_ids
        ]
        blocked = [c.claim_id for c in claims if c.status == "blocked_l1_conflict"]
        downgraded = [c.claim_id for c in claims if c.downgraded]
        if not claims:
            overall_cap = "NONE"
        else:
            min_score = min(TIER_STRENGTH[c.effective_tier] for c in claims)
            overall_cap = STRENGTH_TO_TIER[min_score]

        return {
            "total_l5_claims": len(claims),
            "persisted_claims_available": len(self.l5_claims) - len(claims),
            "overall_confidence_cap": overall_cap,
            "converge_allowed": len(blocked) == 0,
            "blocked_l1_conflicts": blocked,
            "downgraded_claims": downgraded,
            "claims": [c.model_dump() if hasattr(c, 'model_dump') else c.dict() for c in claims],
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
