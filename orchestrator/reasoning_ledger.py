"""Append-only ReasoningRecord ledger with information-flow closure (research P2).

Core mechanism of the structured-interim paper: every reasoning segment is a
schema-validated record whose claims may only cite evidence that was
registered BEFORE the record's timestamp. Post-hoc rationalization cannot
obtain an early timestamp — direction violations are structural, not heuristic.

Storage: traces/reasoning_ledger.jsonl (append-only; mounted read-write in the
backend container). In-process state is rebuilt from the file on first use.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from proxy_gateway.interim_schema import load_schema, validate

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = REPO_ROOT / "traces" / "reasoning_ledger.jsonl"
SCHEMA_NAME = "reasoning-record.schema.json"

# evidence_id -> {"ts": float(epoch), "kind": str}
_state: dict[str, dict[str, Any]] = {}
_records: list[dict[str, Any]] = []
_loaded = False


def _parse_ts(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    if not LEDGER_PATH.exists():
        return
    for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        _apply(entry)


def _apply(entry: dict[str, Any]) -> None:
    if entry.get("type") == "evidence":
        _state[entry["id"]] = {"ts": float(entry["ts"]), "kind": entry.get("kind", "tool_output")}
    elif entry.get("type") == "record":
        rec = entry.get("record") or {}
        _records.append(rec)
        ts = _parse_ts(rec.get("ts"))
        if rec.get("record_id") and ts is not None:
            _state[rec["record_id"]] = {"ts": ts, "kind": "ledger"}


def _append(entry: dict[str, Any]) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    _apply(entry)


def register_evidence(evidence_id: str, ts: Any, kind: str = "tool_output", ref: str | None = None) -> dict[str, Any]:
    """Register an executed-evidence timestamp. ts may be epoch or ISO-8601."""
    _load()
    parsed = _parse_ts(ts)
    if not evidence_id or parsed is None:
        return {"ok": False, "error": "evidence_id and a parseable ts are required"}
    if evidence_id in _state:
        return {"ok": False, "error": f"evidence {evidence_id!r} already registered (ledger is append-only)"}
    entry = {"type": "evidence", "id": evidence_id, "ts": parsed, "kind": kind, "ref": ref or ""}
    _append(entry)
    return {"ok": True, "id": evidence_id, "ts": parsed}


def _closure_violations(record: dict[str, Any], ts: float) -> list[str]:
    violations: list[str] = []

    def _check(ref: str, where: str) -> None:
        ev = _state.get(ref)
        if ev is None:
            violations.append(f"{where}: {ref} not registered (forward reference or unknown)")
        elif ev["ts"] >= ts:
            violations.append(
                f"{where}: {ref} ts {ev['ts']:.3f} >= record ts {ts:.3f} (information-flow violation)"
            )

    for ref in record.get("evidence_refs") or []:
        _check(str(ref), "evidence_refs")
    for i, claim in enumerate(record.get("claims") or []):
        for sid in claim.get("source_ids") or []:
            _check(str(sid), f"claims[{i}].source_ids")
    return violations


def submit_record(record: dict[str, Any]) -> dict[str, Any]:
    """Validate + closure-check + append. Violations reject the record (no write)."""
    _load()
    violations = validate(load_schema(SCHEMA_NAME), record)
    ts = _parse_ts(record.get("ts"))
    if ts is None:
        violations.append("ts: unparseable timestamp (epoch or ISO-8601 required)")
    rid = record.get("record_id")
    if rid and rid in _state:
        violations.append(f"record_id: {rid} already exists (append-only ledger)")
    if ts is not None:
        violations.extend(_closure_violations(record, ts))
    if violations:
        return {"ok": False, "violations": violations, "record_id": rid}
    _append({"type": "record", "record": record})
    return {"ok": True, "record_id": rid, "ledger_size": len(_records)}


def ledger_status() -> dict[str, Any]:
    _load()
    return {"records": len(_records), "evidence_entries": len(_state), "ledger_path": str(LEDGER_PATH)}
