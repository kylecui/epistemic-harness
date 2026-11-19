"""Unified Harness Backend: gateway + MCP-over-HTTP in one process (one port).

Exposes:
  - All proxy gateway routes at / (OpenAI /v1, Anthropic /anthropic, /health, /quota, /traces)
  - POST /mcp/epistemic    Streamable-HTTP-style JSON-RPC bridge to mcp_server (7 tools)
  - POST /mcp/orchestrator Streamable-HTTP-style JSON-RPC bridge to orchestrator (7 tools)

This is the container entrypoint (`harness_backend:app`). The stdio servers remain
available for local/dev use; both transports share the same handle_request logic.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

REPO_ROOT = Path(os.getenv("HARNESS_REPO_ROOT", str(Path(__file__).resolve().parent))).resolve()
if str(REPO_ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(REPO_ROOT))

from mcp_server.dag_engine import EpistemicEngine  # noqa: E402
from mcp_server.server import handle_request as epistemic_handle  # noqa: E402
from orchestrator.server import Orchestrator  # noqa: E402
from orchestrator.server import handle_request as orchestrator_handle  # noqa: E402
from proxy_gateway.app import app as gateway_app  # noqa: E402

MCP_STATE: dict[str, Any] = {"engine": None, "orch": None}


def _engine() -> EpistemicEngine:
    if MCP_STATE["engine"] is None:
        MCP_STATE["engine"] = EpistemicEngine(REPO_ROOT)
    return MCP_STATE["engine"]


def _orch() -> Orchestrator:
    if MCP_STATE["orch"] is None:
        MCP_STATE["orch"] = Orchestrator(REPO_ROOT)
    return MCP_STATE["orch"]


app = FastAPI(title="epistemic-harness-backend", version="0.3.0")


@app.post("/mcp/epistemic")
async def mcp_epistemic(request: Request) -> Any:
    req = await request.json()
    resp = epistemic_handle(_engine(), req)
    if resp is None:
        return JSONResponse({}, status_code=202)
    return JSONResponse(resp)


@app.post("/mcp/orchestrator")
async def mcp_orchestrator(request: Request) -> Any:
    req = await request.json()
    resp = orchestrator_handle(_orch(), req)
    if resp is None:
        return JSONResponse({}, status_code=202)
    return JSONResponse(resp)


@app.get("/mcp/epistemic")
@app.get("/mcp/orchestrator")
async def mcp_get_not_supported() -> Any:
    # MCP streamable HTTP: clients may probe GET for a server-initiated SSE stream.
    # We intentionally do not hold long-lived SSE connections (stateless bridge);
    # 405 + Allow is the spec-correct way to decline. All client calls are POST.
    raise HTTPException(status_code=405, headers={"Allow": "POST"})


@app.get("/mcp/health")
async def mcp_health() -> dict[str, Any]:
    return {
        "epistemic_tools": len((__import__("mcp_server.server", fromlist=["TOOLS"]).TOOLS)),
        "orchestrator_ready": True,
        "repo_root": str(REPO_ROOT),
    }


# Gateway routes take over every remaining path (mounted last).
app.mount("/", gateway_app)

# Back-compat alias (tests import harness_backend.parent).
parent = app
