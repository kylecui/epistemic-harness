# M1 measurements — 2026-11-26

Three measurements on the completed 600-run campaign (5 arms × 6 tasks × 20 samples, SiliconFlow
DeepSeek-V4-Flash subject, judged on the isolated lab plane). Every number is produced by a script in
`experiments/` and can be recomputed.

## 1. The contract's cost is fixed, not proportional

`python experiments/latency_decomp.py` — least squares of `elapsed = a + b·output_chars` per arm:

| arm | n | median chars | median secs | intercept (s) | secs per 1k chars | R² |
|---|---|---|---|---|---|---|
| A | 120 | 1645 | 20.2 | 7.9 | 10.51 | 0.28 |
| A0 | 120 | 2790 | 20.2 | 9.4 | 4.97 | 0.38 |
| B | 119 | 3180 | 47.3 | 18.4 | 10.77 | 0.36 |
| C | 118 | 2782 | 56.7 | 22.0 | 14.88 | 0.30 |
| D | 116 | 2872 | 52.6 | 29.3 | 10.09 | 0.26 |

The contract arms pay a **2.0–3.7× fixed overhead** (intercept 18–29 s vs 8–9 s) while the marginal cost
of writing is comparable (10–15 s per 1k chars; only the direct arm A0 sits at 5.0). "The contract is
slow" therefore means "each call costs a fixed amount more", not "it writes more".

Caveat: R² is 0.26–0.38, so output length explains about a third of the variance, and the intercepts are
an extrapolation from a narrow character range rather than a measured zero-output time.

## 2. Judges from different families barely agree — the arm ranking was not a finding

`python experiments/judge_agreement.py judged-qwen` — DeepSeek-V3.2 (same family as the subject) against
GLM-5.3-Flash (different family), 579 shared samples:

| arm | primary | cross-family | Δ | r | mean abs diff |
|---|---|---|---|---|---|
| A | 0.890 | 0.807 | +0.083 | +0.16 | 0.205 |
| A0 | 0.837 | 0.670 | +0.167 | +0.22 | 0.277 |
| B | 0.839 | 0.775 | +0.064 | +0.22 | 0.198 |
| C | 0.837 | 0.798 | +0.039 | −0.13 | 0.233 |
| D | 0.809 | 0.773 | +0.035 | +0.20 | 0.230 |

Overall **r = +0.15**, 39 % of samples differ by more than 0.2, and the ORDER changes: primary says
A > B ≈ A0 ≈ C > D; cross-family says A > C > B > D > A0 (A0 last). Any arm ranking resting on mean
differences below ~0.1 is withdrawn.

## 3. Anchored rubric: real but insufficient improvement

`--rubric anchored` gives every 0/1 item a 0 example, a 1 example and a tie-break rule, then re-scores
all 600 runs with the cross-family judge:

| arm | n | primary | cross anchored | Δ | r |
|---|---|---|---|---|---|
| A | 117 | 0.891 | 0.733 | +0.157 | +0.42 |
| A0 | 120 | 0.837 | 0.635 | +0.202 | +0.44 |
| B | 118 | 0.837 | 0.786 | +0.051 | +0.14 |
| C | 108 | 0.835 | 0.817 | +0.019 | +0.06 |
| D | 113 | 0.809 | 0.777 | +0.032 | +0.25 |

Overall r rises **+0.15 → +0.28** and per-arm agreement improves for A/A0/D, but the disagreement rate
stays ~38 %. The rubric was part of the problem, not all of it. Anchors become the default for future
judging; no ordering below a 0.1 mean difference is reportable on this data.

## What survives all three judgments

`A > A0` holds everywhere: primary +0.054, cross-family +0.137, cross-family anchored +0.098 — consistent
sign, magnitude above the noise floor. The mechanical (format) measurement is unaffected by judging and
stays the primary metric: `report-extraction` passes 1/20 (A0) and 2/20 (A) against 20/20, 17/18, 19/19
for B/C/D.

## Open

* Per-sample agreement is still 38 %: the next instrument to try is pairwise A/B preference on the same
task (or a stratified human spot-check), not another rubric tweak.
* 13 unanchored and 24 anchored rows have no score because the judge call failed to return JSON; they are
excluded from both means rather than imputed.

