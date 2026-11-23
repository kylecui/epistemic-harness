#!/usr/bin/env python3
"""Zero-dependency MCP JSON-RPC 2.0 stdio server for epistemic-harness (Phase 1).

Works natively with Pi (.pi/mcp.json), OpenCode, Claude Code, Codex, and Cursor.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

# Allow running directly as `python3 mcp_server/server.py`
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import os

from mcp_server.dag_engine import EpistemicEngine
from mcp_server.memory_index import DB_REL as MEMORY_DB_REL, ensure_db, recall as recall_memory

PROTOCOL_VERSION = "2024-11-05"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "query_l1",
        "description": "Query read-only L1 Axioms & Invariants. Models may ONLY cite L1 IDs returned by this tool.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "default": ""}},
        },
    },
    {
        "name": "search_l2",
        "description": "Search L2 Verified Evidence / Library entries with provenance and timestamps.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "default": ""}},
        },
    },
    {
        "name": "recall_l3",
        "description": "Recall L3 Heuristics & Empiricism (always wrapped with mandatory scope_conditions & counter_examples).",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "default": ""}},
        },
    },
    {
        "name": "register_l4_input",
        "description": "Register an L4 human intent or resource constraint into the current session registry.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "input_id": {"type": "string", "description": "Must start with 'L4-', e.g. L4-TEAM-001"},
                "statement": {"type": "string"},
                "kind": {"type": "string", "default": "constraint"},
            },
            "required": ["input_id", "statement"],
        },
    },
    {
        "name": "submit_l5_claim",
        "description": (
            "Submit an L5 interim derivation or conclusion. Hard-enforces source_id existence "
            "(blocks invented L1 axioms), requires every cited L1/L2/L3 source to appear in this "
            "session's retrieval trace (GROUNDING_VIOLATION otherwise), auto-detects uncited L3 "
            "heuristics whose text matches the claim (IMPLICIT_L3_DEPENDENCY, anti-laundering), "
            "and computes transitive weakest-link confidence ceiling in code."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "claim_id": {"type": "string"},
                "claim": {"type": "string"},
                "claimed_tier": {"type": "string", "enum": ["L1", "L2", "L3"]},
                "source_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "retrieval_trace": {"type": "array", "items": {"type": "string"},
                                     "description": "IDs actually returned by query_l1/search_l2/recall_l3"},
                "assumptions": {"type": "array", "items": {"type": "string"}},
                "conflicts_with_l1": {"type": "array", "items": {"type": "string"}},
                "external_cause_required": {"type": "boolean", "default": False},
            },
            "required": ["claim_id", "claim", "claimed_tier", "source_ids"],
        },
    },
    {
        "name": "audit_dag",
        "description": "Audit the full session L5 derivation DAG, returning overall confidence cap and L1 conflict blocks.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "query_l5",
        "description": (
            "Recall prior L5 derivations from the persisted append-only store (knowledge/l5_store/*.jsonl). "
            "Reusing a claim inherits its effective_tier as a hard cap; cite claim_id instead of re-deriving."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "default": ""},
                "limit": {"type": "integer", "default": 5},
            },
        },
    },
    {
        "name": "recall_memory",
        "description": (
            "Hybrid keyword retrieval (SQLite FTS5: ASCII words + CJK bigrams) over the memory banks. "
            "Returns L1/L2/L3/L5 banks SEPARATELY with status flags (stale for expired L2) — tiers are "
            "never blended into one score."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "default": ""},
                "k": {"type": "integer", "default": 3},
                "tiers": {"type": "array", "items": {"type": "string", "enum": ["L1", "L2", "L3", "L5"]}},
            },
        },
    },
    {
        "name": "propose_promotion",
        "description": "Queue a verified L3/L5 item for human PR review to promote to L1 or L2 (never writes directly).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_id": {"type": "string"},
                "target_tier": {"type": "string", "enum": ["L1", "L2"]},
                "rationale": {"type": "string"},
            },
            "required": ["source_id", "target_tier", "rationale"],
        },
    },
]


def handle_request(engine: EpistemicEngine, req: dict[str, Any]) -> dict[str, Any] | None:
    req_id = req.get("id")
    method = req.get("method")
    params = req.get("params") or {}

    # Notifications (no id) do not receive responses
    if req_id is None and method and method.startswith("notifications/"):
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "epistemic-mcp", "version": "0.1.0"},
            },
        }

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            if name == "query_l1":
                res = engine.query_l1(args.get("query", ""))
            elif name == "search_l2":
                res = engine.search_l2(args.get("query", ""))
            elif name == "recall_l3":
                res = engine.recall_l3(args.get("query", ""))
            elif name == "register_l4_input":
                res = engine.register_l4_input(
                    args["input_id"], args["statement"], args.get("kind", "constraint")
                )
            elif name == "submit_l5_claim":
                res = engine.submit_l5_claim(args)
            elif name == "audit_dag":
                res = engine.audit_dag(include_persisted=bool(args.get("include_persisted", False)))
            elif name == "recall_memory":
                store = Path(os.environ.get("HARNESS_MEMORY_STORE") or REPO_ROOT)
                db = store / MEMORY_DB_REL
                ensure_db(db, REPO_ROOT / "knowledge")
                res = recall_memory(db, args.get("query", ""), int(args.get("k", 3)), args.get("tiers"))
            elif name == "query_l5":
                res = engine.query_l5(args.get("query", ""), int(args.get("limit", 5)))
            elif name == "propose_promotion":
                res = engine.propose_promotion(
                    args["source_id"], args["target_tier"], args["rationale"]
                )
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {name}"},
                }
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=2)}],
                    "isError": False,
                },
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"HARD_CONSTRAINT_ERROR: {exc}"}],
                    "isError": True,
                },
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    engine = EpistemicEngine(REPO_ROOT)
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
        else:
            resp = handle_request(engine, req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
