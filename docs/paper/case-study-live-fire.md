# Case study: one day of live fire — the enforcement layer vs. its own authors

> Research artifact for the paper (paper §: "Deployment experience" or a
> standalone case-study section). Every row traces to a committed regression
> test and a commit hash. Date: 2026-11-22. Location: this repository,
> production session (the authors' own daily harness use).

## Why this case study matters for the paper

The paper claims two things: (1) deterministic enforcement beats prompt-only
contracts, and (2) the blocker for enforcement is **precision**, not
detection. Both claims were tested not on synthetic benchmarks but on the
authors themselves, for one full working day, with the enforcement layer
enabled on its own development session. The result is a seven-class taxonomy
of false positives, one architectural gap, and one design principle upgrade —
each closed with a regression test.

This is the strongest available answer to a reviewer's obvious question:
"your checks are regexes; won't they fire on everything?" — the live answer:
they fired on seven identifiable patterns, all of which are now impossible,
and the suite grew 254 → 281 tests in the process.

## Timeline (all times local, 2026-11-22)

| # | Class | Trigger observed live | Fix (commit) | Regression test |
|---|---|---|---|---|
| 1 | Version-number anchors | "P1.6 完成" parsed as defect P1 | ba1cec4 | test_pnumber_false_positive.py |
| 2 | Intercept quote loop | Quoting a bounce re-flagged its bullets; 3 consecutive bounces | ba1cec4 | test_intercept_quote_loop.py |
| 3 | Short-status overreach | 5-line status report bounced for missing sections | ba1cec4 | test_intercept_quote_loop.py |
| 4 | Multi-site multiplication | 6 unsynchronized check call sites, no dedup; 1 turn accumulated 3 intercept blocks, counts doubled per turn | 0286e64 | test_intercept_dedup.py |
| 5 | Bare prose mentions | "缺陷项 P1", "P2 回环" parsed as declarations | 0286e64 | test_intercept_dedup.py |
| 6 | Inline-code mentions | "`缺陷1:` 才算声明" parsed as a declaration | edb2a91 | test_intercept_dedup.py |
| 7 | Mid-sentence label mentions | "我反复写 [L3] 依据配 L2 头" parsed as two unscoped labels | 61c8db1 | test_intercept_dedup.py |

Architectural findings in the same window:

- **A1 — the loop had no production caller** (b59627d): the Python engine's
  review check was correct but unreachable; the production turn-end enforcer
  is the client extension, which had no review-contract path at all. Lesson:
  *an enforcement layer without a wired caller is a pseudo-contract* (the
  repo's own issue-#3 vocabulary). Fix: `--review-check` CLI + TS wiring,
  bounce-once-then-halt.
- **A2 — cap is computed, not self-declared** (fbc1054): the single most
  repeated violation (~5 times by the same author in one session) was the
  model declaring an L2 header over L3-body content. Bouncing did not change
  the habit; aligning the header to the computed weakest layer did. This is
  the repo's first principle (harness.yaml L5) applied to the output contract
  itself: *the ceiling is deterministically computed in code*.
- **A3 — forensics before fixes** (8f988bb): after chasing phantom violations
  through session logs by hand, every judgment now writes
  `{layer, code_rev, violations, text_sha256}` to a trace file. Every
  subsequent incident was root-caused from the trace in minutes. Lesson:
  *an enforcement layer needs a flight recorder to be maintainable*.

## Quantitative residue

- Test suite grew 254 → 281 (+27 regression tests) during the exercise.
- Violation taxonomy: 7 false-positive classes closed; the remaining
  intercept classes are genuine obligations (missing deliverable structure,
  incomplete defect plans) and are exactly the ones the paper's E4 suites
  measure precision on (0/7 clean-claim false-flags, 3/3 solid plans pass).
- Each class was found in production, not in review: median time from first
  observation to fix-with-regression ≈ one turn.

## Claims this case study supports in the paper

1. Contribution 2 (precision engineering): the taxonomy IS the engineering
   method — adversarial suites catch classes 4–7 a priori; classes 1–3 and
   A1–A3 only surface under live load, which is why the paper pairs suite
   precision numbers with a deployment narrative.
2. Contribution 1 (enforcement as infrastructure): A1 shows enforcement has
   to be wired at every layer that can end a turn; a correct-but-unreachable
   check is indistinguishable from absence.
3. The OmO contrast (shadow vs blocking) gains a third data point: their
   changelog reports high false-positive rates in shadow mode; our live-fire
   day shows the FP classes are enumerable and closable, which is what makes
   blocking viable.
