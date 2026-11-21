"""Memory reuse statistics (G6): does persisted memory actually earn its keep?

The loop ledger records `memory_refs` (ids cited in run_gate claims). This module
turns those records into the two numbers the memory system needs:

  * hit ratio — how often tasks reference persisted memory;
  * archive candidates — L5 claims nobody cited within the retention window.

Archive = move to knowledge/l5_store/archive/ (kept, not deleted — forgetting
moves things out of the active index, it does not erase them).
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

RETENTION_DAYS = 90


def ledger_memory_refs(ledger_path: Path, window: int = 500) -> list[tuple[str, str]]:
    """Return [(claim_id, ts)] cited by gate runs, newest first."""
    if not ledger_path.exists():
        return []
    refs: list[tuple[str, str]] = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("kind") != "gate":
            continue
        ts = str(rec.get("ts") or "")
        for ref in rec.get("memory_refs") or []:
            refs.append((str(ref), ts))
    return refs[-window:]


def l5_claim_ids(l5_dir: Path) -> dict[str, str]:
    """Map claim_id -> latest created_at (or mtime fallback) for the active store."""
    out: dict[str, str] = {}
    if not l5_dir.exists():
        return out
    for path in sorted(l5_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            cid = rec.get("claim_id")
            if cid:
                out[str(cid)] = str(rec.get("created_at") or "")[:10]
    return out


def stats(repo_root: Path, retention_days: int = RETENTION_DAYS) -> dict[str, Any]:
    """hit ratio + archive candidates for the active L5 store."""
    root = Path(repo_root)
    ledger = root / ".pi" / "loop_ledger.jsonl"
    l5_dir = root / "knowledge" / "l5_store"

    refs = ledger_memory_refs(ledger)
    cited: dict[str, str] = {}
    for cid, ts in refs:
        cited.setdefault(cid, ts)

    total_tasks = 0
    if ledger.exists():
        total_tasks = sum(
            1 for line in ledger.read_text(encoding="utf-8").splitlines()
            if '"kind": "gate"' in line
        )
    citing_tasks = len({ts for _, ts in refs})

    claims = l5_claim_ids(l5_dir)
    today = datetime.now(timezone.utc).date()
    candidates: list[dict[str, Any]] = []
    for cid, created in claims.items():
        age = None
        try:
            age = (today - datetime.strptime(created, "%Y-%m-%d").date()).days
        except ValueError:
            age = retention_days + 1  # unknown age -> archive candidate, conservatively
        last_cited = cited.get(cid)
        if last_cited is None and (age is None or age > retention_days):
            candidates.append({"id": cid, "age_days": age, "reason": "never_cited_and_old"})

    ratio = round(citing_tasks / total_tasks, 3) if total_tasks else 0.0
    return {
        "gate_runs": total_tasks,
        "runs_citing_memory": citing_tasks,
        "hit_ratio": ratio,
        "distinct_cited": sorted(cited),
        "active_l5_claims": len(claims),
        "archive_candidates": candidates,
    }


def archive(repo_root: Path, retention_days: int = RETENTION_DAYS) -> dict[str, Any]:
    """Move archive candidates into knowledge/l5_store/archive/ (reversible)."""
    root = Path(repo_root)
    report = stats(root, retention_days)
    if not report["archive_candidates"]:
        return {"moved": 0, "report": report}
    l5_dir = root / "knowledge" / "l5_store"
    archive_dir = l5_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    targets = {c["id"] for c in report["archive_candidates"]}
    moved = 0
    for month_file in sorted(l5_dir.glob("*.jsonl")):
        kept: list[str] = []
        for line in month_file.read_text(encoding="utf-8").splitlines():
            try:
                cid = json.loads(line).get("claim_id")
            except json.JSONDecodeError:
                kept.append(line)
                continue
            if cid in targets:
                with (archive_dir / month_file.name).open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
                moved += 1
            else:
                kept.append(line)
        month_file.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    return {"moved": moved, "report": report}
