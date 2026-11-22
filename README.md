# Epistemic & Dual-Process Governance Harness

**Governance for LLM coding agents: evidence-bound claims, tiered cognition, and loops that exhaust problems instead of ping-ponging them.**

[![version](https://img.shields.io/badge/version-v0.4.0-blue)](docs/workplan-v0.4.md)
[![tests](https://img.shields.io/badge/tests-237%20green-brightgreen)](scripts/verify.py)
[![license](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

*中文介绍见 [README_ZH.md](README_ZH.md)。 All normative content (rules, contracts, skills) is English-only; Chinese exists only as auxiliary translation.*

## What it does

An LLM agent inside this harness cannot silently:

- **claim completion without evidence** — quantified claims ("100% coverage", "all tests pass") must bind to a check the exit gate executed itself, or the gate blocks the turn (issue #2);
- **ask you to decide things that are already decided** — a raised "decision point" must carry an L4 trade-off or a missing-evidence anchor, otherwise it is bounced as a fabricated decision (issue #3);
- **dismiss failures** — buck-passing phrasing is intercepted only while verification is red, and every failure gets an owner: `code_defect / check_defect / env_missing / underdetermined`;
- **cheat the verifier** — the verifier's own fingerprint is recorded; a green run right after the verifier changed is flagged;
- **repeat the same fix forever** — a cross-turn ledger escalates identical failure fingerprints to root-cause analysis.

Agents also get: an L1–L5 epistemic memory with weakest-link confidence caps, hybrid retrieval (BM25 + CJK bigrams, per-tier banks that never blend), a data-driven task router (per-category model/effort decisions in YAML, validated against a capability matrix), three dispatch tiers (text-only / read-only sandboxed explorer / full tooled), and Docker-first verification with a declared host fallback.

## Quickstart

```bash
git clone https://github.com/kylecui/epistemic-harness.git
cd epistemic-harness

python scripts/install.py        # detect platform, prerequisites, ASKS FOR API KEYS, smoke test
docker compose up -d --build     # start the gateway backend (127.0.0.1:8787)
pi                               # start Pi in the repo (loads AGENTS.md + MCP)
```

The installer reads the model registry and prompts for exactly the provider keys
your configured models need (Enter keeps existing values; everything is skippable).
Prefer editing by hand? Put keys in `.env` instead — see
[docs/configuration.md](docs/configuration.md).

Two lighter paths if you do not want the full setup yet:

```bash
# Fastest: verification only — no venv, no install; the container IS the runtime
docker compose build verify && docker compose run --rm verify

# Minimal on the host: bootstrap python only, then the installer does the rest
python scripts/install.py
```

Verify at any time — the `hvx` wrapper resolves the project interpreter for you
(`.venv` first, then `python3`/`py`; verification itself runs in Docker by default):

```bash
./scripts/hvx                      # or: scripts\hvx.ps1 on Windows
./scripts/hvx -p "test_gate*"      # unittest discovery pattern
```

## How it fits together

| Layer | Component | Enforced by |
|---|---|---|
| Contract | `harness.yaml` → compiled `AGENTS.md` / `SKILL.md` | prompt + gateway |
| Exit gate | `orchestrator/exit_gate.py` + `extensions/harness-guard.ts` (mirror) | deterministic code |
| Verification runner | `scripts/verify.py`, `Dockerfile.verify` | docker-first, host fallback |
| Epistemic core | `mcp_server/` (L1–L5 DAG, FTS5 memory, L5 persistence) | MCP tools |
| Orchestration | `orchestrator/` (dispatch, routing, plans, read-only explorer) | MCP tools + gateway routing |
| Docs | `docs/` (index: [docs/README.md](docs/README.md)) | `scripts/check_docs.py` in the exit gate |

## Skills: commands you don't have to remember

`harness-verify` (./scripts/hvx), `harness-status` (dispatches / capability matrix /
memory stats), `harness-maintain` (recompile + revalidate after config edits), and
`harness-config` (provider keys, default model, pins) are registered in
`skills/registry.yaml` — matched and auto-attached by code at dispatch time, in
English and Chinese. Query them any time via the orchestrator MCP (`query_skills`).

## Documentation

- [INSTALL.md](INSTALL.md) — platform detection, prerequisites, full/limited support matrix
- [docs/configuration.md](docs/configuration.md) — LLM provider keys, default model selection, pins
- [docs/README.md](docs/README.md) — documentation index
- [docs/execution-runner.md](docs/execution-runner.md) — why verification runs in Docker first
- [docs/browser-runner.md](docs/browser-runner.md) — where the browser goes for CDP work
- [docs/workplan-v0.4.md](docs/workplan-v0.4.md) — v0.4 delivery log with measured evidence

## Development

```bash
git clone https://github.com/kylecui/epistemic-harness.git
cd epistemic-harness
./scripts/hvx                                # 206 tests, docker by default
python evals/run_evals.py --mock             # golden-case regression (12/12)
python scripts/check_eol.py                  # line-ending policy
python scripts/check_docs.py                 # docs/code sync gate
python scripts/analyze_dispatches.py         # what was delegated, to which model, at what effort
python scripts/capability_matrix.py          # the (model × effort) schedulable space
```

MIT licensed. See [LICENSE](LICENSE).
