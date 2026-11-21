"""Memory retrieval (G3): per-tier banks over SQLite FTS5, never blended.

Why this shape:
  * Tiers are a lattice, not a similarity score. L1 must be recallable without a
    top-k gamble, and an L3 hit must stay visibly L3. So the index keeps `tier`
    as a column and `recall()` returns banks separately — no weighted fusion,
    which would be silent promotion in code.
  * BM25 (FTS5) is enough to start: a minimal hybrid retriever reached parity
    with prior SOTA memory systems at a fraction of the cost (arXiv:2611.22179,
    read 2026-11-21). Adding embeddings is a later, measurable step.
  * Chinese text needs tokenization: FTS5's unicode61 splits on punctuation and
    keeps CJK runs whole, so we index CJK bigrams alongside ASCII words. No
    external segmenter, no network.
  * Forgetting is explicit: L2 entries past `max_age_days` come back as `stale`,
    they are never silently dropped or silently trusted.

Everything here is stdlib (sqlite3 + json + yaml for the source files).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

import yaml

DB_REL = Path("knowledge") / "memory_index.db"
L2_MAX_AGE_DAYS = 180
_CJK = re.compile(r"[\u3400-\u9fff]+")
_ASCII = re.compile(r"[a-z0-9_\-]{2,}")


def tokenize(text: str) -> str:
    """ASCII words + CJK bigrams (and unigrams for single-character runs)."""
    low = (text or "").lower()
    tokens: list[str] = _ASCII.findall(low)
    for run in _CJK.findall(low):
        if len(run) == 1:
            tokens.append(run)
            continue
        tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
        tokens.append(run)  # keep the whole run too: exact phrase matches
    seen: list[str] = []
    for tok in tokens:
        if tok not in seen:
            seen.append(tok)
    return " ".join(seen)


@dataclass
class MemoryItem:
    id: str
    tier: str
    title: str
    one_line: str
    body: str
    keywords: str
    scope: str
    counter: str
    source: str
    verified_at: str

    def as_row(self) -> tuple:
        keywords = " ".join(x for x in (self.keywords, self.source) if x)
        return (
            self.id, self.tier, self.title, self.one_line, self.body, keywords,
            self.scope, self.counter, self.source, self.verified_at,
            tokenize(" ".join([self.title, self.one_line, self.body, keywords, self.scope])),
        )


def _yaml_items(path: Path, key: str, tier: str) -> list[MemoryItem]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: list[MemoryItem] = []
    for raw in data.get(key) or []:
        body = " ".join(
            str(raw.get(k) or "") for k in ("statement", "fact", "claim", "description", "correction")
        ).strip()
        out.append(MemoryItem(
            id=str(raw.get("id") or "?"),
            tier=tier,
            title=str(raw.get("title") or raw.get("name") or ""),
            one_line=(body or str(raw.get("title") or ""))[:200],
            body=body,
            keywords=" ".join(
                [str(s) for s in (raw.get("scope_conditions") or [])][:3]
                + [str(c) for c in (raw.get("counter_examples") or [])][:2]
                + [str(m) for m in (raw.get("detection_markers") or [])][:6]
            ),
            scope="; ".join(str(s) for s in (raw.get("scope_conditions") or [])),
            counter="; ".join(str(c) for c in (raw.get("counter_examples") or [])),
            source=str(raw.get("source") or ""),
            verified_at=str(raw.get("verified_at") or ""),
        ))
    return out


def _l5_items(l5_dir: Path) -> list[MemoryItem]:
    out: list[MemoryItem] = []
    if not l5_dir.exists():
        return out
    seen: set[str] = set()
    for path in sorted(l5_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            cid = rec.get("claim_id")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            sources = ", ".join(rec.get("source_ids") or [])
            out.append(MemoryItem(
                id=str(cid),
                tier="L5",
                title=f"L5 ({rec.get('effective_tier', '?')})",
                one_line=str(rec.get("claim") or "")[:200],
                body=str(rec.get("downgrade_reason") or ""),
                keywords=sources,
                scope="",
                counter="",
                source=sources,
                verified_at=str(rec.get("created_at") or "")[:10],
            ))
    return out


def collect_items(knowledge_dir: Path) -> list[MemoryItem]:
    items: list[MemoryItem] = []
    items += _yaml_items(knowledge_dir / "l1_axioms" / "axioms.yaml", "axioms", "L1")
    items += _yaml_items(knowledge_dir / "l2_library" / "evidence.yaml", "evidence", "L2")
    items += _yaml_items(knowledge_dir / "l3_heuristics" / "heuristics.yaml", "heuristics", "L3")
    items += _yaml_items(knowledge_dir / "l3_heuristics" / "cognitive_biases.yaml", "biases", "L3")
    items += _l5_items(knowledge_dir / "l5_store")
    return items


SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY, tier TEXT NOT NULL, title TEXT, one_line TEXT, body TEXT,
    keywords TEXT, scope TEXT, counter TEXT, source TEXT, verified_at TEXT, tokens TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
    id UNINDEXED, tier UNINDEXED, title, one_line, body, keywords, tokens, tokenize='unicode61'
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA)
    return conn


def build(db_path: Path, knowledge_dir: Path) -> dict[str, Any]:
    items = collect_items(knowledge_dir)
    conn = connect(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM items")
            conn.execute("DELETE FROM items_fts")
            for item in items:
                row = item.as_row()
                conn.execute(
                    "INSERT INTO items (id, tier, title, one_line, body, keywords, scope, counter,"
                    " source, verified_at, tokens) VALUES (?,?,?,?,?,?,?,?,?,?,?)", row)
                conn.execute(
                    "INSERT INTO items_fts (id, tier, title, one_line, body, keywords, tokens)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (item.id, item.tier, item.title, item.one_line, item.body, item.keywords, row[-1]))
    finally:
        conn.close()
    by_tier: dict[str, int] = {}
    for item in items:
        by_tier[item.tier] = by_tier.get(item.tier, 0) + 1
    return {"db": str(db_path), "items": len(items), "by_tier": by_tier,
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


ROUTE_RULES = (
    (("定义", "定理", "不变量", "恒等式", "axiom", "invariant"), ["L1", "L2", "L5"]),
    (("事实", "观测", "日志", "数据", "telemetry", "doc", "证据"), ["L2", "L1", "L3"]),
    (("设计", "选型", "方案", "最佳", "架构", "compare", "trade-off"), ["L3", "L2", "L5"]),
    (("之前", "上次", "已证明", "结论", "earlier", "prior"), ["L5", "L2", "L3"]),
)


def route(query: str) -> dict[str, Any]:
    """Pick which banks to query, in what order — never blend their scores."""
    banks = ["L1", "L2", "L3", "L5"]
    low = (query or "").lower()
    for keywords, order in ROUTE_RULES:
        if any(k in low for k in keywords):
            banks = order
            break
    return {
        "banks": banks,
        "k_per_bank": 3,
        "rule": "banks are queried separately and returned separately; tier is never blended "
                "into one score (blending would be silent promotion)",
    }


def _age_days(stamp: str) -> int | None:
    if not stamp:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            when = datetime.strptime(stamp[:19] if "T" in stamp else stamp[:10], fmt.split("T")[0] if fmt.startswith("%Y-%m-%d") else fmt)
        except ValueError:
            continue
        if when.tzinfo:
            when = when.astimezone(timezone.utc).replace(tzinfo=None)
        return (datetime.now(timezone.utc).replace(tzinfo=None) - when).days
    return None


def recall(db_path: Path, query: str, k: int = 3, tiers: list[str] | None = None) -> dict[str, Any]:
    plan = route(query)
    banks = tiers or plan["banks"]
    conn = connect(db_path)
    try:
        out: dict[str, list[dict[str, Any]]] = {}
        for tier in banks:
            rows: list[sqlite3.Row] = []
            toks = tokenize(query)
            if toks:
                fts_query = " OR ".join(toks.split())
                try:
                    rows = conn.execute(
                        "SELECT i.* FROM items_fts f JOIN items i ON i.id = f.id "
                        "WHERE items_fts MATCH ? AND i.tier = ? ORDER BY bm25(items_fts) LIMIT ?",
                        (fts_query, tier, k),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []
            if not rows and query:
                like = f"%{query}%"
                rows = conn.execute(
                    "SELECT * FROM items WHERE tier = ? AND (title LIKE ? OR one_line LIKE ? "
                    "OR body LIKE ? OR keywords LIKE ? OR source LIKE ?) LIMIT ?",
                    (tier, like, like, like, like, like, k),
                ).fetchall()
            if not rows and not query:
                rows = conn.execute("SELECT * FROM items WHERE tier = ? LIMIT ?", (tier, k)).fetchall()
            bank: list[dict[str, Any]] = []
            for row in rows:
                rec = dict(zip([c[0] for c in conn.execute("SELECT * FROM items LIMIT 0").description], row))
                age = _age_days(rec.get("verified_at", ""))
                status = "ok"
                if tier == "L2" and age is not None and age > L2_MAX_AGE_DAYS:
                    status = "stale"
                bank.append({
                    "id": rec["id"], "tier": tier, "title": rec["title"],
                    "one_line": rec["one_line"], "source": rec["source"],
                    "verified_at": rec["verified_at"], "age_days": age,
                    "scope": rec["scope"], "counter_examples": rec["counter"],
                    "status": status,
                })
            out[tier] = bank
        return {
            "query": query,
            "route": plan,
            "banks": out,
            "policy": (
                "L1 hits may be cited by id only. L2 hits prove observed facts; `stale` means "
                f"older than {L2_MAX_AGE_DAYS} days and must be re-verified before use. "
                "L3 hits are candidate hypotheses: carry scope + counter-examples and cap any "
                "derived conclusion at L3. L5 hits inherit their recorded effective tier."
            ),
        }
    finally:
        conn.close()


def ensure_db(db_path: Path, knowledge_dir: Path) -> dict[str, Any]:
    """Build when missing, then report the state (used by the MCP tool)."""
    if not db_path.exists():
        return build(db_path, knowledge_dir)
    conn = connect(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    finally:
        conn.close()
    source_count = len(collect_items(knowledge_dir))
    if count != source_count:
        return build(db_path, knowledge_dir)
    return {"db": str(db_path), "items": count, "rebuilt": False}
