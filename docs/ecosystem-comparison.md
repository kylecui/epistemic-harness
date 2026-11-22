# Ecosystem comparison — evidence-bound completion governance (evidence-gap remediation)

> Date: 2026-11-22. **Two rounds.** Round 1: README-level keyword scan (method
> and limits below). Round 2 (same day, after the round-1 verdict proved
> insufficient): code-level audit via `git clone --depth 1` of all four repos +
> ripgrep over code, docs and CHANGELOGs. OmO's CHANGELOG turned out to be the
> load-bearing evidence — the README scan had missed it.

## Question under review

The v0.5 review claimed a whitespace: agent frameworks do routing, quota,
memory and dispatch, but almost none enforce "a completion claim must bind to
a check the gate executed this turn". Does that claim survive a code-level
look?

## Round-1 result (superseded — kept for honesty)

README-level scan: none of OmO / aider / SWE-agent / OpenHands *advertises*
claim-to-evidence governance. aider's hits were unrelated ('evidence' in
unrelated contexts); SWE-agent and OpenHands scored zero. **Verdict at
advertising level: whitespace holds.** Limitation stated then: README absence
≠ code absence. That limitation fired.

## Round-2 result (code-level, 2026-11-22)

**The whitespace claim is REFUTED for OmO.** Its CHANGELOG documents a
first-class claim-receipts subsystem that is the same mechanism as this
repo's exit gate:

| Evidence | Source (OmO CHANGELOG, depth-1 clone + rg) |
|---|---|
| Turn-final "tests pass / done" claims checked against a session check that passed after the last code edit; claim recorded as backed/unbacked. Shipped in **shadow mode** (no display, no blocking) because one week of internal sessions produced mostly false-positive flags; a nudge note + gate reviewer activate only behind `omo-senpi-claim-receipt-nudge`. | PR #10785 |
| `bun check` counted as type-check evidence so a "typecheck passed" claim is no longer "unverified". | PR #11794 |
| Claim receipts parse runner argv strictly (echo argv no longer earns a test receipt). | PR #11542 |
| ulw-research requires every conclusion to rest on something a tool observed; workers tag claims `OBSERVED:` / `PROBED:`. | PR #12832 |
| ulw-research ships a machine-readable fact ledger, fidelity state file and claim index for research reports. | PR #11046 |
| DAG parent-side verification directive: "treat the claim as false until proven"; verify nodes gate every produced file. | #7080 / changelog |

aider / SWE-agent / OpenHands: no equivalent mechanism found at code level in
this audit (zero hits for exit-gate / claim-receipt / done-gate patterns;
OpenHands' confirmation mode is human approval, not evidence binding).
**Limitation:** single-day audit, main branch only, pattern-list based; a
semantically different implementation could evade the patterns used.

## Revised positioning (what actually differentiates this repo)

OmO occupies the *detection* space in shadow mode. This repo's delta:

1. **Enforcement, not shadow**: claims unbound to executed checks block the
   turn (exit gate bounce), with a verifier-fingerprint tamper record and
   failure-class attribution — none of which appear in OmO's record.
2. **Measured precision on adversarial suites**: our substance checks score
   0/7 clean-claim false-flags (anti-laundering) and 3/3 solid-plan passes
   (hollow suite). OmO's own note says most shadow flags were false positives;
   a precision comparison is a concrete, measurable paper contribution.
3. **Broader claim surface**: quantified/completeness claims, contract
   structure (falsifiable acceptance, named rollback), epistemic tier caps —
   beyond "tests pass / done".
4. **Deterministic open implementation** the paper can ablate.

Paper framing update: from "nobody does claim-to-evidence" (refuted) to
"from shadow-mode claim detection to deterministic enforcement: precision and
effect measured" (defensible, and OmO PR #10785 becomes the key citation).

Anchors retrieved 2026-11-22 (arXiv list from round 1 remains in git history;
OmO evidence stored as L2-OMO-001 in knowledge/l2_library/evidence.yaml).
