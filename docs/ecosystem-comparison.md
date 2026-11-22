# Ecosystem comparison — evidence-bound completion governance (evidence-gap remediation)

> Date: 2026-11-22. Method: README-level keyword scan via GitHub raw/API (no
> auth), plus repository metadata. **Limitation (read this first):** absence of
> a keyword in a README is NOT proof the feature does not exist in code. This
> scan validates the *positioning claim* ("nobody advertises evidence-bound
> completion claims"); it is not a code-level audit of competitor repos. The
> paper-grade version of this table needs `zread`-style repo doc/code search.

## Question under review

The review (2026-11-22) claimed a whitespace: agent frameworks do routing,
quota, memory and dispatch, but almost none enforce "a completion claim must
bind to a check the gate executed this turn". Does that claim survive a
first external look?

## Findings

| Project | Stars | Evidence | README signals for claim-to-evidence governance |
|---|---|---|---|
| oh-my-openagent (OmO) | 71,050 | repo API, `pushed_at` 2026-11-22 (active) | none: no exit-gate / evidence-bound / completion-claim terms in README (14 hits were unrelated 'verify' words; 0 for the specific patterns) |
| aider | — | raw README | 0 hits for exit-gate / evidence-bound patterns |
| SWE-agent | — | raw README | 0 hits |
| OpenHands | — | raw README | 0 hits for the claim-evidence patterns; README does not advertise it (OpenHands has confirmation/approval flows, a different mechanism: human gating, not evidence binding) |

## Verdict

**Holds at README/advertising level [L2, scoped]:** none of the four most
popular agent frameworks advertises or documents evidence-bound completion
claims, verifier-fingerprint tamper detection, or failure-fingerprint
attribution. The positioning whitespace for the paper (contribution 1:
"claim-to-check binding as deterministic infrastructure") is still open as of
2026-11-22.

**Not verified [honest gap]:** code-level presence in private branches /
recently added features. Remediation before any paper submission: run
`zread search_doc` (or clone + ripgrep) against these four repos for
`exit.?gate|verifier|claim.*check|done.?gate` in code, not just READMEs.
Activation condition: before paper submission, not before v0.5 release.

## Related-work anchors for the paper (retrieved 2026-11-22, arXiv API)

- Confidence calibration: "Calibrating the Confidence of Large Language Models
  by Eliciting Fidelity" — models' self-reported confidence is unreliable;
  external calibration needed.
- Self-verification limits: "A Closer Look at the Self-Verification Abilities
  of Large Language Models in Logical Reasoning" — self-verification degrades
  exactly when problems get hard.
- Process rewards: "Verifiable Process Rewards for Agentic Reasoning";
  "MAS-ProVe"; "Lean4AgenticRL" — process-level verification is an active
  research line, but framed as RL reward, not as runtime governance.
- Agent memory: "Graph-based Agent Memory: Taxonomy, Techniques, and
  Applications"; arXiv:2611.22179 "RAG in a Trenchcoat" — memory should be
  evaluated by what it enables an agent to do.
