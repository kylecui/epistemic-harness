#!/usr/bin/env python3
"""Zero-dependency MCP JSON-RPC 2.0 stdio server: Epistemic Orchestrator (Phase 3).

Tools exposed to the main agent (controller):
  classify_task       - advisory tier/profile classification for a subtask
  dispatch_subagent   - execute one subtask via the proxy gateway (auto-attaches skills)
  query_skills        - search the skill registry
  register_skill      - queue a new skill for human approval (never writes live registry)
  submit_l5_claim     - shared-session L5 derivation DAG (weakest-link cap)
  audit_dag           - converge gate: overall confidence cap + L1 conflict blocks
  bias_scan           - deterministic cognitive-bias first-pass screen (L3 heuristic)
  plan_task           - decompose a task into subtasks with tier/profile + dependency waves
  run_plan            - execute the plan: create sub-agents (parallel waves, context passing)
  dispatch_tooled     - run one TOOLED sub-agent (isolated pi process, can read/write/run)
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp_server.dag_engine import EpistemicEngine
from orchestrator.bias_guard import BiasGuard
from orchestrator.dispatch import dispatch_subtask
from orchestrator.plan import plan_task, run_plan
from orchestrator.tooled import dispatch_tooled
from orchestrator.planner import classify_task
from orchestrator.skills import SkillRegistry

PROTOCOL_VERSION = "2024-11-05"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "classify_task",
        "description": "Classify a subtask into a cognitive tier + sub-agent profile (advisory; gateway re-enforces the same tier).",
        "inputSchema": {
            "type": "object",
            "properties": {"task_text": {"type": "string"}},
            "required": ["task_text"],
        },
    },
    {
        "name": "dispatch_subagent",
        "description": (
            "Execute one delegated subtask through the proxy gateway under an agent profile "
            "(explorer/coder/deep/critic). Matching skills are auto-attached to the sub-agent prompt."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_profile": {"type": "string", "enum": ["explorer", "coder", "deep", "critic"]},
                "task_text": {"type": "string"},
                "context": {"type": "string", "default": ""},
                "task_id": {"type": "string", "default": "default"},
            },
            "required": ["agent_profile", "task_text"],
        },
    },
    {
        "name": "bias_scan",
        "description": (
            "Deterministic first-pass cognitive-bias screen on any text (L3 heuristic, "
            "false positives possible). Hits must be escalated to a critic-profile dispatch for verdict."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "plan_task",
        "description": (
            "Decompose a task into subtasks (deterministic heuristics; conservative single-subtask fallback). "
            "Returns per-subtask tier/profile, auto-attached skills, dependency waves. Advisory — review before run_plan."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"task_text": {"type": "string"}},
            "required": ["task_text"],
        },
    },
    {
        "name": "run_plan",
        "description": (
            "Create and run sub-agents per plan: parallel waves execute concurrently, dependent subtasks "
            "receive upstream results as context. Omit subtasks to auto-plan from task_text. "
            "Each sub-agent gets its own profile-pinned tier/model via the gateway."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_text": {"type": "string", "default": ""},
                "subtasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "task_text": {"type": "string"},
                            "agent_profile": {"type": "string", "enum": ["explorer", "coder", "deep", "critic"]},
                            "depends_on": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["task_text"],
                    },
                },
                "escalate_on_bias": {"type": "boolean", "default": False},
                "synthesize": {"type": "boolean", "default": False},
                "timeout": {"type": "number", "default": 300},
            },
        },
    },
    {
        "name": "dispatch_tooled",
        "description": (
            "Run a TOOLED sub-agent in an isolated pi process (separate context/session, hard timeout). "
            "Use it for real implementation work in a workspace: it can read/write files and run commands, "
            "unlike dispatch_subagent which is text-only. Host-side only (requires the pi binary)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_text": {"type": "string"},
                "workdir": {"type": "string", "description": "Workspace directory (defaults to repo root)"},
                "profile": {"type": "string", "enum": ["explorer", "coder", "deep", "critic"], "default": "coder"},
                "model": {"type": "string"},
                "timeout": {"type": "number", "default": 600},
            },
            "required": ["task_text"],
        },
    },
    {
        "name": "query_skills",
        "description": "Search the skill registry by keyword (id/name/description/tags/triggers).",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "default": ""}, "limit": {"type": "integer", "default": 5}},
        },
    },
    {
        "name": "register_skill",
        "description": "Queue a new skill into skill_queue/pending.yaml for human approval (never writes the live registry).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "content": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "triggers": {"type": "array", "items": {"type": "string"}},
                "tier_hint": {"type": "string"},
            },
            "required": ["name", "description", "content"],
        },
    },
    {
        "name": "submit_l5_claim",
        "description": "Submit an L5 interim derivation; code enforces source existence and weakest-link cap.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "claim_id": {"type": "string"},
                "claim": {"type": "string"},
                "claimed_tier": {"type": "string", "enum": ["L1", "L2", "L3"]},
                "source_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "assumptions": {"type": "array", "items": {"type": "string"}},
                "conflicts_with_l1": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["claim_id", "claim", "claimed_tier", "source_ids"],
        },
    },
    {
        "name": "audit_dag",
        "description": "Audit the shared-session L5 DAG: overall confidence cap, converge_allowed, L1 conflicts.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


class Orchestrator:
    def __init__(self, repo_root: Path) -> None:
        self.engine = EpistemicEngine(repo_root)
        self.skills = SkillRegistry(
            repo_root / "skills" / "registry.yaml",
            repo_root / "skill_queue" / "pending.yaml",
        )
        self.bias_guard = BiasGuard(repo_root / "knowledge" / "l3_heuristics" / "cognitive_biases.yaml")

    def classify_task(self, task_text: str) -> dict[str, Any]:
        return classify_task(task_text, skills_matcher=self.skills.match_for_task)

    def plan_task(self, task_text: str) -> dict[str, Any]:
        return plan_task(task_text, skills_matcher=self.skills.match_for_task)

    def run_plan(self, args: dict[str, Any]) -> dict[str, Any]:
        return run_plan(
            task_text=str(args.get("task_text", "")),
            subtasks=args.get("subtasks"),
            escalate_on_bias=bool(args.get("escalate_on_bias", False)),
            synthesize=bool(args.get("synthesize", False)),
            timeout=float(args.get("timeout", 300)),
            skills_matcher=self.skills.match_for_task,
            engine=self.engine,
        )

    def dispatch_subagent(self, args: dict[str, Any]) -> dict[str, Any]:
        attached = self.skills.match_for_task(args["task_text"])
        return dispatch_subtask(
            agent_profile=args["agent_profile"],
            task_text=args["task_text"],
            context=args.get("context", ""),
            task_id=args.get("task_id", "default"),
            attached_skills=attached,
            escalate_on_bias=bool(args.get("escalate_on_bias", False)),
        )

    def dispatch_tooled(self, args: dict[str, Any]) -> dict[str, Any]:
        return dispatch_tooled(
            task_text=str(args["task_text"]),
            workdir=args.get("workdir"),
            profile=str(args.get("profile", "coder")),
            model=args.get("model"),
            timeout=float(args.get("timeout", 600)),
        )

    def query_skills(self, query: str, limit: int = 5) -> dict[str, Any]:
        return {"skills": self.skills.query(query, limit=limit)}

    def register_skill(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.skills.register_pending(
            name=args["name"],
            description=args["description"],
            content=args["content"],
            tags=args.get("tags"),
            triggers=args.get("triggers"),
            tier_hint=args.get("tier_hint"),
        )


def handle_request(orch: Orchestrator, req: dict[str, Any]) -> dict[str, Any] | None:
    req_id = req.get("id")
    method = req.get("method")
    params = req.get("params") or {}

    if req_id is None and method and method.startswith("notifications/"):
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "epistemic-orchestrator", "version": "0.3.0"},
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            if name == "classify_task":
                res = orch.classify_task(args["task_text"])
            elif name == "dispatch_subagent":
                res = orch.dispatch_subagent(args)
            elif name == "query_skills":
                res = orch.query_skills(args.get("query", ""), int(args.get("limit", 5)))
            elif name == "register_skill":
                res = orch.register_skill(args)
            elif name == "submit_l5_claim":
                res = orch.engine.submit_l5_claim(args)
            elif name == "audit_dag":
                res = orch.engine.audit_dag()
            elif name == "bias_scan":
                res = orch.bias_guard.scan(args["text"])
            elif name == "plan_task":
                res = orch.plan_task(args["task_text"])
            elif name == "run_plan":
                res = orch.run_plan(args)
            elif name == "dispatch_tooled":
                res = orch.dispatch_tooled(args)
            else:
                return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown tool: {name}"}}
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=2)}], "isError": False},
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": f"ORCHESTRATOR_ERROR: {exc}"}], "isError": True},
            }
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def main() -> None:
    orch = Orchestrator(REPO_ROOT)
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
        else:
            resp = handle_request(orch, req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
