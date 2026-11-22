# Paper package: From shadow-mode claim detection to deterministic enforcement

> Status: research working notes on `feature/v0.5-quality-program` (not for
> merge to master until submission-ready). All numbers trace to committed
> reports in `evals/reports/` (2026-11-22 runs, glm-5.3 unless noted).
> Date of this package: 2026-11-22.

## Working title

**From Shadow to Gate: Deterministic Enforcement of Evidence-Bound Completion
Claims in LLM Coding Agents**

## One-paragraph thesis

Agent frameworks increasingly detect false completion claims ("all tests
pass", "done") but, in the one system that ships this at scale (OmO,
71k★), the detector runs in shadow mode because its false-positive rate was
too high to enforce against. We show the gap is closed by (a) expanding the
claim surface with deterministic structure checks (falsifiable acceptance,
named rollback, epistemic tier caps), (b) enforcing at the transport/tool
layer instead of nudging, and (c) measuring both precision and effect on
adversarial suites. On 5-trial × multi-scenario inducement experiments the
enforcement layer halves false-completion rates on implementation tasks
(80%→40%, 40%→20%) where a prompt-only contract leaves them unchanged on
unverifiable-completeness claims (40%→40%) — demonstrating precisely which
failure classes require in-loop claim binding.

## Contribution claims (each must map to a section + a committed artifact)

1. **Claim-to-check binding as blocking infrastructure** — exit gate with
   verifier-fingerprint tamper detection and failure-class attribution
   (code/check/env/underdetermined). Artifact: `orchestrator/exit_gate.py`,
   `extensions/harness-guard.ts`, TC-10/11.
2. **Precision-engineered contract checks** — substance filters over anchor
   keywords: measured 0/7 clean-claim false-flags (anti-laundering suite) and
   3/3 solid-plan pass (hollow suite), vs the incumbent's self-reported
   majority-false-positive shadow flags (OmO PR #10785 note).
   Artifacts: `tests/test_l5_grounding_adversarial.py`,
   `tests/test_hollow_compliance_adversarial.py`.
3. **Measured enforcement effect** — 5-trial inducement experiment,
   baseline vs harness: FC-02 80%→40%, FC-01 40%→20%, FC-03 40%→40%.
   Artifact: `evals/reports/false_completion_*`.
4. **Measured protocol fragility of prompt-only contracts** — flagship model
   passes strict golden matrix only 11/30 across 5 trials; two distinct
   failure modes (protocol skipping, false conflict declaration). Motivates
   deterministic enforcement. Artifact: `evals/reports/real_matrix_*`.

## Target venues (ranked)

1. NeurIPS / ICLR agent workshop (positioning + system + measurements fit
   workshop format; full ablation can extend to a main-track submission).
2. ACL/EMNLP Findings (if framed as calibration/verification of agent
   outputs; NLP audience values the false-completion measurement).
3. ICSE / FSE tool track (if framed as a engineering-governance tool with
   user study; needs a human factor we don't have yet — see gaps).

## Section skeleton

1. **Introduction** — false completion claims as an agent-reliability
   failure class; OmO's shadow-mode admission as motivation; our thesis.
2. **Related work** — see `related-work.md`.
3. **System** — three enforcement layers (prompt contract / transport
   gateway / tool-level DAG + exit gate); the claim taxonomy (quantified,
   completeness, structural, epistemic-tier); anti-laundering design
   (retrieval-trace grounding, implicit L3 dependency detection).
4. **Precision methodology** — adversarial suites as the evaluation unit;
   numbers from suites.
5. **Effect methodology** — inducement scenarios; baseline/harness
   isolation; honest scope notes (transport active in both modes).
6. **Results** — see `experiments.md` for the full tables.
7. **Threats to validity** — single flagship model (+1 secondary), n=5,
   post-hoc measurement without in-loop gate on FC, parametric-memory
   confound in memory experiments, regex-language coverage (zh/en/ja/ko).
8. **Discussion** — which failure classes enforcement catches vs which need
   in-loop binding (FC-03 result); cost of enforcement (token/延迟 overhead
   to be measured — see gaps).
9. **Reproducibility** — open repo, committed reports, deterministic suites.

## Gaps — ALL CLOSED 2026-11-22 (user decision: close before merge)

- In-loop gate ablation → E5: gate arm 0/20 false completions; FC-03 class
  (unmoved post-hoc) reaches zero under blocking enforcement.
- OmO detector comparison → E7: reference-rule recall 0.82 vs our 1.0 on the
  same corpus; documented-rule shape misses the unbound-claim class.
- Cost analysis → E8: +3.8k input tokens, +216 ms, 0.155 ms/check.
- Cross-model replication → E6: kimi 18/30 vs glm 11/30; TC-03 0/10 across
  both models (protocol-teachability finding).

Remaining pre-submission work is writing-only: draft the full §1–§9 prose from
this package; no new measurements are gated.
