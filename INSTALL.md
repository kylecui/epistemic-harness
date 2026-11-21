# Installation

Installation ships with the release — it is designed, platform-aware, and honest about degradation. Nothing silently falls back.

## 1. One-command setup

```bash
python scripts/install.py          # detect, set up, smoke test (idempotent)
python scripts/install.py --check  # report only, change nothing
```

## 2. Platform detection

`install.py` probes the host and prints a capability matrix:

```
platform   : Windows-11-10.0.26340-SP0
shell      : posix-via-git-bash | posix | windows-native
python     : 3.12.3 (>=3.10: True)
git        : True
docker     : True
venv       : True
support    : FULL | LIMITED
```

## 3. Support matrix

| Tier | Requirements | What you get |
|---|---|---|
| **FULL** | Docker + git + Python ≥ 3.10 | Container-first verification (POSIX shell, pinned image, `--network none`), backend via `docker compose`, batch-docker checks, every feature |
| **LIMITED** | Python ≥ 3.10, no Docker | Host-runner verification with an explicit warning; see the LIMITED SUPPORT list printed by the installer |

### LIMITED SUPPORT list (no Docker)

The installer prints this list and it applies until Docker is available:

- verification runs on the **host shell** (cmd.exe/PowerShell vs POSIX sh): shell-dependent checks may behave differently;
- **no container isolation**: checks share the host filesystem and process space;
- **batch-docker disabled**: one process per check instead of one container per batch;
- **image-pinned determinism unavailable**: verdicts record `runner=host` only;
- **higher CRLF risk**: the eol pre-commit hook still applies, but `.gitattributes` is the only git-side guard.

Without git: residue scan and the pre-commit eol hook are disabled (listed separately).

## 4. What the installer does

1. creates `.venv` and installs `requirements.txt`;
2. installs the versioned pre-commit hook (`core.hooksPath=scripts/git-hooks`, sets `core.autocrlf=false`);
3. compiles the client contract (`AGENTS.md`, Gemini prompt, portable `SKILL.md`) from `harness.yaml`;
4. builds the verify image (`epistemic-verify:local`) when Docker is present — skipped with a warning otherwise;
5. builds the memory index (`knowledge/memory_index.db`);
6. runs the smoke test (`scripts/verify.py`).

## 5. Backend (optional but recommended)

```bash
docker compose up -d --build     # gateway + MCP-over-HTTP on 127.0.0.1:8787
curl 127.0.0.1:8787/health       # {"status":"ok", ...}
```

The backend exposes OpenAI-compatible `/v1`, Anthropic-compatible `/anthropic`, and MCP endpoints (`/mcp/epistemic`, `/mcp/orchestrator`). Any MCP-capable client can connect without local Python.

## 6. Client wiring

- **Pi**: project-level `.pi/mcp.json` (repo) and `~/.pi/agent/mcp.json` (user) already point at `127.0.0.1:8787`. Start Pi inside the repo to load `AGENTS.md` and the guard extension.
- **Claude Code / OpenCode**: `scripts/install_research_mcp.py --target claude|opencode` (research MCP servers, no secrets in the repo).
- Verify with `pi mcp list`.

## 7. Verifying the installation

```bash
python scripts/verify.py                 # 197 tests (docker by default, host fallback)
python scripts/check_docs.py             # docs/code sync gate
python scripts/analyze_dispatches.py     # dispatch observability
```
