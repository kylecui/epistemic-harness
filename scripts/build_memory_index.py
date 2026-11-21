#!/usr/bin/env python3
"""Generate knowledge/INDEX.md — the cheap first layer of memory retrieval.

Reading the whole YAML store into every prompt is wasteful; reading nothing means
the agent re-derives what it already proved. The index gives one line per item
(id | tier | one-line | keywords) so a caller can decide what to expand, while
`get_item`-style tools (query_l1 / search_l2 / recall_l3 / query_l5) return the
full record on demand.

Usage:
    python scripts/build_memory_index.py            # rewrite knowledge/INDEX.md
    python scripts/build_memory_index.py --check    # exit 1 when stale (CI)
    python scripts/build_memory_index.py --db       # (re)build knowledge/memory_index.db
`--check` exits 1 when the committed index is stale (CI-friendly).
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE = REPO_ROOT / "knowledge"
OUT = KNOWLEDGE / "INDEX.md"


def _one_line(item: dict) -> str:
    for key in ("statement", "fact", "claim", "description", "title"):
        value = str(item.get(key) or "").strip().replace("\n", " ")
        if value:
            return value if len(value) <= 90 else value[:87] + "..."
    return ""


def _keywords(item: dict, limit: int = 5) -> str:
    bits: list[str] = []
    bits.extend(str(s) for s in (item.get("scope_conditions") or [])[:2])
    bits.extend(str(c) for c in (item.get("counter_examples") or [])[:1])
    if item.get("source"):
        bits.append(str(item["source"]))
    if item.get("verified_at"):
        bits.append(f"verified {item['verified_at']}")
    text = " / ".join(b.replace("\n", " ") for b in bits if b)
    return text if len(text) <= 110 else text[:107] + "..."


def _load(path: Path, key: str) -> list[dict]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get(key) or []


def _l5_store_summary() -> list[dict]:
    store = KNOWLEDGE / "l5_store"
    rows: list[dict] = []
    if not store.exists():
        return rows
    seen: set[str] = set()
    for path in sorted(store.glob("*.jsonl")):
        for raw in path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            cid = rec.get("claim_id")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            rows.append(rec)
    return rows


def render() -> str:
    lines = [
        "# Knowledge Index (generated — do not edit)",
        "",
        f"> Built {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} by `scripts/build_memory_index.py`.",
        "> Read this index first; expand only the ids the current task needs.",
        "",
    ]
    tiers = [
        ("L1 · Axioms & Hard Invariants (read-only, cite-only)", "l1_axioms/axioms.yaml", "axioms"),
        ("L2 · Verifiable Evidence", "l2_library/evidence.yaml", "evidence"),
        ("L3 · Heuristics (each carries scope + counter-examples)", "l3_heuristics/heuristics.yaml", "heuristics"),
    ]
    for title, rel, key in tiers:
        items = _load(KNOWLEDGE / rel, key)
        lines += [f"## {title} — {len(items)} item(s)", ""]
        if not items:
            lines += ["_(empty)_", ""]
            continue
        lines += ["| id | one-line | keywords / limits |", "|---|---|---|"]
        for item in items:
            lines.append(f"| `{item.get('id', '?')}` | {_one_line(item)} | {_keywords(item)} |")
        lines.append("")

    biases = _load(KNOWLEDGE / "l3_heuristics" / "cognitive_biases.yaml", "biases")
    lines += [f"## L3 · Cognitive Bias Screen — {len(biases)} pattern(s)", ""]
    if biases:
        lines += ["| id | trigger markers | harness mitigation |", "|---|---|---|"]
        for b in biases:
            markers = ", ".join(str(m) for m in (b.get("detection_markers") or [])[:6])
            lines.append(
                f"| `{b.get('id', '?')}` {b.get('name', '')} | {markers} | "
                f"{(b.get('harness_mapping') or '')[:80]} |"
            )
        lines.append("")

    l5 = _l5_store_summary()
    lines += [f"## L5 · Persisted Derivations — {len(l5)} claim(s)", ""]
    if l5:
        lines += ["| id | effective tier | claim | sources |", "|---|---|---|---|"]
        for rec in l5:
            sources = ", ".join(rec.get("source_ids") or [])
            lines.append(
                f"| `{rec.get('claim_id')}` | {rec.get('effective_tier', '?')} | "
                f"{_one_line({'claim': rec.get('claim', '')})} | {sources} |"
            )
        lines.append("")
        lines.append("Reusing a persisted claim inherits its `effective_tier` as a hard cap — cite the id, do not re-derive.")
    else:
        lines.append("_(none yet — `submit_l5_claim` appends here automatically)_")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    if "--db" in sys.argv:
        sys.path.insert(0, str(REPO_ROOT))
        from mcp_server.memory_index import DB_REL, build  # noqa: E402
        summary = build(REPO_ROOT / DB_REL, KNOWLEDGE)
        print(f"memory db: {summary['items']} item(s) {summary['by_tier']} -> {DB_REL.as_posix()}")
        return 0

    content = render()
    check = "--check" in sys.argv
    if check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        # Ignore the build timestamp line when comparing.
        strip = lambda s: "\n".join(l for l in s.splitlines() if not l.startswith("> Built "))
        if strip(current) != strip(content):
            print("knowledge/INDEX.md is stale; run: python scripts/build_memory_index.py")
            return 1
        print("knowledge/INDEX.md is up to date.")
        return 0
    OUT.write_text(content, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
