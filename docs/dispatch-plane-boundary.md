# The dispatch plane boundary (issues #7, #9)

Two planes exist and must not be confused for each other:

| Plane | Where | What it can see |
|---|---|---|
| container | `harness-backend` (:8787), orchestrator MCP server | its image plus the selective mounts in `docker-compose.yml` |
| host | your terminal, the repo worktree | everything you can read and write |

## A sub-agent cannot just "read the worktree" (#7)

The orchestrator runs inside the container, so `D:\MyWorkSpaces\...` does not exist there. Mounting
the host filesystem into the gateway was rejected: it trades a convenience for a security surface
the architecture deliberately avoids. The tooled tiers cross the boundary through a host-side agent:

```
container orchestrator --loopback--> scripts/host_dispatch.py (127.0.0.1:8791) --> host paths
```

- Start it yourself: `python scripts/host_dispatch.py --serve --roots "D:\MyWorkSpaces;C:\Users\you"`
- The allowlist (`--roots`, default: your home) is enforced after resolving symlinks; anything
  outside returns `outside_allowlist` with HTTP 403.
- Every result names its plane and transport: `runner=host|container`, `via=in-process|host_dispatch`.
  When the agent is down the error is `host_dispatch_unavailable` plus the start command.

## A verification command cannot run "where the gate runs" (#9)

`run_gate` used to execute caller commands inside the backend container, whose `/app` holds the image
plus a few mounts, so `python tests/test_plane_alignment.py` failed with "No such file or directory"
and the verdict was `no_evidence` even when the command passed on the host.

`orchestrator/exit_gate.py` now detects the plane it is on, resolves every path a command mentions,
refuses with `plane_mismatch` when a path is not visible from that plane, and otherwise runs the
command through the same sandbox the exit gate uses — so the verdict names the runner that produced it.

## Rule of thumb

Reads and writes of the host worktree go through the host agent. Verification of the repo runs in the
verify container. A tool that silently does the opposite is a defect, not a convenience.
