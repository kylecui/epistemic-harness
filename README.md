# Epistemic & Dual-Process Governance Harness

**Governance for LLM coding agents: evidence-bound claims, tiered cognition, and loops that exhaust problems instead of ping-ponging them.**

[![version](https://img.shields.io/badge/version-v0.4.0-blue)](docs/workplan-v0.4.md)
[![tests](https://img.shields.io/badge/tests-197%20green-brightgreen)](scripts/verify.py)
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
python scripts/install.py        # detect platform, prerequisites, set up, smoke test
docker compose up -d --build     # start the gateway backend (127.0.0.1:8787)
pi                               # start Pi in the repo (loads AGENTS.md + MCP)
```

Verify at any time:

```bash
python scripts/verify.py                     # full test suite (docker by default)
python scripts/analyze_dispatches.py         # what was delegated, to which model, at what effort
python scripts/capability_matrix.py          # the (model × effort) schedulable space
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

## Documentation

- [INSTALL.md](INSTALL.md) — platform detection, prerequisites, full/limited support matrix
- [docs/README.md](docs/README.md) — documentation index
- [docs/execution-runner.md](docs/execution-runner.md) — why verification runs in Docker first
- [docs/browser-runner.md](docs/browser-runner.md) — where the browser goes for CDP work
- [docs/workplan-v0.4.md](docs/workplan-v0.4.md) — v0.4 delivery log with measured evidence

## Development

```bash
python -m unittest discover -s tests     # 197 tests
python evals/run_evals.py --mock         # golden-case regression (12/12)
python scripts/check_eol.py              # line-ending policy
python scripts/check_docs.py             # docs/code sync gate
```

MIT licensed. See [LICENSE](LICENSE).
