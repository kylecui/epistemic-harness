# Documentation Index

Normative content (rules, contracts, skills) is English-only; a Chinese auxiliary translation may accompany operational docs. Anything listed here is current at v0.4.0 — `scripts/check_docs.py` fails the exit gate on orphan or stale entries.

## Operational (current behavior)

| Doc | What it covers |
|---|---|
| [../INSTALL.md](../INSTALL.md) | Platform detection, prerequisites, FULL/LIMITED support matrix, installer walkthrough |
| [configuration.md](configuration.md) | LLM provider keys, default model selection (routing chains), per-category/request pins, adding a provider |
| [execution-runner.md](execution-runner.md) | Docker-first verification: why, measured numbers, the POSIX-alignment preconditions |
| [dispatch-plane-boundary.md](dispatch-plane-boundary.md) | Which plane a dispatch or a verification command runs on, and why crossing it silently is a defect (issues #7, #9) |
| [research/m1-measurements-2026-11-26.md](research/m1-measurements-2026-11-26.md) | The three M1 measurements: fixed contract cost, cross-family judge disagreement, anchored rubric |
| [router-operations.md](router-operations.md) | Blue/green topology, the upgrade order, rollback, and the commands that are now forbidden — replaces every earlier `docker compose up -d --build` instruction |
| [browser-runner.md](browser-runner.md) | Browser/CDP placement policy: container vs host, evidence, Windows constraints |
| [research-capability.md](research-capability.md) | External retrieval before design answers: research MCP servers, fallbacks, grounding check |
| [ecosystem-comparison.md](ecosystem-comparison.md) | Evidence-gap remediation: README-level scan of OmO/aider/SWE-agent/OpenHands for claim-to-evidence governance (2026-11-22, with stated limits) |

| [paper/paper15-m1-dataset.md](paper/paper15-m1-dataset.md) | Paper 1.5 dataset section: what the 600-run M1 campaign contains, how each judgement is attached, and how to recompute it |
| [paper/](paper/) | Paper package (research branch only): outline, experiment record, related work, draft abstract |
| [RELEASE-NOTES.md](RELEASE-NOTES.md) | Per-version user-facing changes; the startup banner prints the current version's section once |
| [ISSUE-PLAN-2026-11-25.md](ISSUE-PLAN-2026-11-25.md) | Remediation plan for the open issues: triage (open / stale / environment / wontfix), batches ordered by blocking risk, acceptance check per issue |





| [UPGRADE.md](UPGRADE.md) | In-place upgrade for existing installs: protected state, idempotent migrations, rollback, support tiers |
| [install-evidence.md](install-evidence.md) | Real install tests (WSL + remote) with transcripts and the 7 defects they exposed |
| [skills-inventory.md](skills-inventory.md) | Skill registry inventory and disposition |
| [language-gravity-anti-jargon-report.md](language-gravity-anti-jargon-report.md) | Style A/B evaluation report (buzzword leakage) |

## Design records (v0.4 cycle)

| [workplan-v0.4.md](workplan-v0.4.md) | v0.4 delivery log §7–§13: every change with its test and measured evidence; final acceptance table |
| [exit-gate-anti-shirking-design.md](exit-gate-anti-shirking-design.md) | Exit gate and anti-shirking design (v0.4.0) |
| [review-remediation-plan.md](review-remediation-plan.md) | Review findings → fixes mapping (P0/P1/P2 cycle) |
| [cognitive-bias-correction-design.md](cognitive-bias-correction-design.md) | Bias catalog → harness mechanisms mapping |

## Historical (Phase 0–3, kept for provenance — not updated)

| [phase0-gem-poc-spec-and-tests.md](phase0-gem-poc-spec-and-tests.md) | Phase 0 Gem PoC spec |
| [phase1-pi-scaffold-guide.md](phase1-pi-scaffold-guide.md) | Phase 1 Pi scaffold guide |
| [phase2-proxy-quota-routing-guide.md](phase2-proxy-quota-routing-guide.md) | Phase 2 proxy + quota routing |
| [phase3-orchestrator-guide.md](phase3-orchestrator-guide.md) | Phase 3 orchestration |
| [epistemic-reasoning-harness-blueprint.html](epistemic-reasoning-harness-blueprint.html) | Original blueprint (HTML) |
