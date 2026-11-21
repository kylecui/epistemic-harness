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

0. prompts for provider API keys — the list is derived from the model registry
   (`api_key_env` entries in `proxy_gateway/quota_policy.yaml`), so it always
   matches your configured models; answers are written to `.env` (skippable,
   `--with-keys` forces the prompt in non-interactive shells);
1. creates `.venv` and installs `requirements.txt`;
2. installs the versioned pre-commit hook (`core.hooksPath=scripts/git-hooks`, sets `core.autocrlf=false`);
3. compiles the client contract (`AGENTS.md`, Gemini prompt, portable `SKILL.md`) from `harness.yaml`;
4. builds the verify image (`epistemic-verify:local`) when Docker is present — skipped with a warning otherwise;
5. builds the memory index (`knowledge/memory_index.db`);
6. offers shell integration — `harness` launcher + `hvx` alias into your PowerShell
   profile / `.bashrc` / `.zshrc` (idempotent, marked blocks; `install.py --with-shell`
   applies, default prints where it would go). cmd.exe gets instructions, not magic.
7. runs the smoke test via the `hvx` wrapper (`scripts/verify.py`).

## 5. Backend (optional but recommended)

```bash
docker compose up -d --build     # gateway + MCP-over-HTTP on 127.0.0.1:8787
curl 127.0.0.1:8787/health       # {"status":"ok", ...}
```

The backend exposes OpenAI-compatible `/v1`, Anthropic-compatible `/anthropic`, and MCP endpoints (`/mcp/epistemic`, `/mcp/orchestrator`). Any MCP-capable client can connect without local Python.

## 6. Client wiring (compatibility matrix)

The backend speaks standard MCP-over-HTTP plus OpenAI/Anthropic-compatible
transports, so most agents can use it. What differs per client is which
enforcement layers apply:

| Layer | Pi | OpenCode | Claude Code | Codex / Cursor / any MCP client |
|---|---|---|---|---|
| MCP tools (`query_l1` … `run_gate`, dispatch, routing) | ✓ | ✓ (verified 2026-11-21) | ✓ | ✓ (spec-standard HTTP MCP) |
| Gateway transport (tier routing, quota, effort clamps, response contract) | ✓ | ✓ | ✓ | ✓ (point the client at `/v1` or `/anthropic`) |
| Contract prompt (`AGENTS.md`) | ✓ auto-loaded | ✓ auto-loaded | ✓ auto-loaded | paste `clients/skills/.../SKILL.md` if the client has no AGENTS.md support |
| Exit-gate auto-enforcement (turn bounce, residue scan, anti-shirking intercept) | ✓ (harness-guard extension) | — | — | — (call the `run_gate` MCP tool explicitly at task completion) |

Per-client wiring:

```bash
# Pi: already wired — repo .pi/mcp.json + user ~/.pi/agent/mcp.json; verify with `pi mcp list`

# OpenCode (verified live, both servers connect):
opencode mcp add epistemic-harness   --url http://127.0.0.1:8787/mcp/epistemic
opencode mcp add epistemic-orchestrator --url http://127.0.0.1:8787/mcp/orchestrator
opencode mcp list

# Claude Code:
claude mcp add -s user -t http epistemic-harness http://127.0.0.1:8787/mcp/epistemic
claude mcp add -s user -t http epistemic-orchestrator http://127.0.0.1:8787/mcp/orchestrator

# Codex (~/.codex/config.toml):            # Cursor (~/.cursor/mcp.json):
# [mcp_servers.epistemic-harness]          # { "mcpServers": {
# url = "http://127.0.0.1:8787/mcp/epistemic"   #   "epistemic-harness": { "url": "http://127.0.0.1:8787/mcp/epistemic" },
# [mcp_servers.epistemic-orchestrator]     #   "epistemic-orchestrator": { "url": "http://127.0.0.1:8787/mcp/orchestrator" } } }
# url = "http://127.0.0.1:8787/mcp/orchestrator"

# Research MCP servers (web search/reader/repo docs) for any of them:
python scripts/install_research_mcp.py --target claude|opencode   # no secrets in the repo
```

Clients other than Pi: keep the exit gate meaningful by calling `run_gate` (with
`claims` bound to checks) at task completion — see `docs/execution-runner.md`.

## 7. Verifying the installation

```bash
./scripts/hvx                            # 205 tests (docker by default, host fallback)
docker compose run --rm verify           # pure-container path: zero host Python needed
python scripts/check_docs.py             # docs/code sync gate
python scripts/analyze_dispatches.py     # dispatch observability
```

`hvx` (or `scripts\hvx.ps1` on Windows) resolves the project interpreter for
you — `.venv` first, then `python3`/`py`. With Docker available you can skip
the host interpreter entirely via the compose command above.
