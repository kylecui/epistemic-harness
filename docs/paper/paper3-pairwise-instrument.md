# Paper 3 — the pairwise preference instrument (design, not yet run)

The measurement section ends by naming the next instrument. This is that instrument's design, written
before running it so the result cannot be shaped after the fact.

## Why not another rubric revision

Absolute 0–1 scoring collapsed under cross-family judging (κ ≈ 0.10; 38 % of samples differ by > 0.2).
Anchoring lifted ordinal α to 0.234 and still left the disagreement rate unchanged. The failure is in the
task we set the judge — "score this answer" — not in the wording of the items: two raters with different
internal thresholds will always disagree on borderline cases, and a five-item average hides that.

## What to run

**Blind, matched, forced choice.** For each task, take one answer from a reference arm and one from a
treatment arm, present both with arm labels and model identity removed, order randomised, and ask only
"which answer better satisfies the task?" with no rubric text.

* Pairs are matched on `(task, sample index)`, so both answers come from the same prompt and the same
  subject model — the only difference is the harness path.
* Each pair is judged **twice per judge**, once in each order, so position bias is measurable rather than
  assumed symmetric. A judge that prefers whichever answer appears first is flagged, not averaged.
* Arms compared: `A0` vs `B` (contract effect) and `A` vs `B` (contract effect net of the gateway). `A` vs
  `A0` is a control that should be near-ties if the gateway alone does not change quality.

## How to read it

Bradley–Terry over the pair outcomes gives a per-arm strength, but the headline number is the **win rate
with a confidence interval**, because it needs no model of the judge:

| Quantity | Decision rule |
|---|---|
| win rate for B over A0 | report as win rate ± 95 % CI; a CI that straddles 0.5 is a tie |
| position-bias rate | share of pairs where the first-shown answer wins; > 60 % invalidates that judge |
| judge agreement | κ between the two judges on the same pairs; this replaces the rubric-based κ |

A result is reportable when the win-rate CI excludes 0.5 **and** the position-bias rate is below the
threshold **and** both judges agree on the direction. Anything else is reported as inconclusive, which is
an acceptable outcome for this instrument.

## Cost

240 pairs per comparison (6 tasks × 20 matched pairs × 2 orders), two judges → 960 judge calls per
comparison. At the lab plane's measured ≈1.4 s per call, that is ≈25 minutes and well inside the ¥60 cap.

## What this instrument still cannot do

* It ranks answers, it does not explain why — a win tells us the treatment is preferred, not which property
  caused it. Ablations stay necessary.
* Bias is minimised, not eliminated: a judge may still prefer length or formatting. Recording answer length
  per pair lets that be checked afterwards, and length should be reported next to every win rate.
* It shares the subject model and the task set with the absolute-rubric study, so it inherits those limits.
