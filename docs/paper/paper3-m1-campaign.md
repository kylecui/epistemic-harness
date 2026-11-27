# Paper 3 — the A0–D campaign: format compliance vs judged outcome

Source data: `experiments/runs/` (600 runs), recomputable with
`experiments/{aggregate,latency_decomp,judge_agreement}.py`. Frozen at tag
`paper-data-freeze-2026-11-26`.

## Design

Five arms, one subject model, six tasks, twenty samples per cell (600 runs):

| Arm | Harness path | Purpose |
|---|---|---|
| A0 | provider API directly, no gateway | the zero-governance baseline |
| A | through the gateway, no contract | isolates the gateway from the contract |
| B/C/D | gateway + structured-interim contract, three variants | the treatment |

Subject: DeepSeek-V4-Flash on the isolated lab plane. Primary judge: DeepSeek-V3.2. Cross-family judge:
GLM-5.3-Flash. Both judges scored every run twice — plain rubric, then anchored rubric.

## Primary outcome: format compliance (deterministic)

The mechanical check is a regex over the answer, so it cannot drift between judges or models. It is the
only measurement here with no rater variance. `report-extraction`, the task whose answer shape is spelled
out in the prompt:

| arm | pass |
|---|---|
| A0 | 1/20 |
| A | 2/20 |
| B | 20/20 |
| C | 17/18 |
| D | 19/19 |

Aggregate mechanical pass across all six tasks: A 78 %, A0 81 %, B 100 %, C 99 %, D 95 %.

Two statements are stable: the contract lifts format compliance to near-ceiling where a shape is
checkable, and the gateway alone does not (A ≈ A0 on that task).

## Secondary outcome: judged quality, and why we do not rank arms on it

Judge means (plain rubric): A 0.890, A0 0.837, B 0.839, C 0.837, D 0.809 — a spread small enough to
invite a ranking. It does not survive inspection:

* **Cross-family disagreement.** GLM-5.3-Flash re-scored the same 579 answers: per-sample Pearson
  r = +0.15, 39 % of samples differ by more than 0.2, and the ORDER changes (cross-family puts A0 last
  at 0.670; primary puts it mid-pack).
* **The right statistic.** On five binary items the correct agreement measures are Cohen's κ and
  Krippendorff's α, not Pearson: κ = +0.104 (plain) / +0.091 (anchored); ordinal α = +0.125 / +0.234.
  Both sit far below the 0.667 that content analysis normally demands.
* **Anchoring helps partially.** Giving each item a 0 example, a 1 example and a tie-break rule lifts
  overall r to +0.28 and ordinal α to +0.234, but the per-sample disagreement rate stays ~38 %.

What survives all four judge configurations: **A > A0** (+0.054 primary, +0.137 cross-family, +0.098
cross-family anchored). Everything else — B vs C vs D, A vs B — is inside the noise floor, and the paper
says so rather than reporting the comparison that looks significant.

## Cost: the contract's price is fixed, not proportional

Least squares of `elapsed = a + b·chars` per arm:

| arm | intercept (s) | s per 1k chars | R² |
|---|---|---|---|
| A | 7.9 | 10.51 | 0.28 |
| A0 | 9.4 | 4.97 | 0.38 |
| B | 18.4 | 10.77 | 0.36 |
| C | 22.0 | 14.88 | 0.30 |
| D | 29.3 | 10.09 | 0.26 |

The contract arms pay a 2.0–3.7× fixed overhead per call while the marginal cost of writing is
comparable. “2.3–2.8× slower” therefore decomposes into “each call costs more”, not “it writes more”.
Caveat: R² 0.26–0.38 — length explains a third of the variance, and the intercepts are an extrapolation
from a narrow character range, not a measured zero-output latency.

## The pairwise result: the contract wins exactly where the task specifies a shape

The absolute rubric could not rank the arms (κ ≈ 0.10). A blind, matched, forced-choice instrument can,
and it was run on 238 pairs (A0 vs B) and 236 pairs (A vs B), each judged twice — once per order — so
position bias is measured rather than assumed. Ties were 1 and 2 respectively; position-bias share was
0.55 and 0.47, both close enough to 0.5 to trust the verdicts.

| Comparison | win rate for B | 95 % CI | reading |
|---|---|---|---|
| A0 (direct) vs B (contract) | 0.283 | [0.229, 0.343] | B loses decisively |
| A (gateway) vs B (contract) | 0.227 | [0.178, 0.284] | B loses decisively |

Per task, the aggregate hides the actual finding:

| task | B win rate vs A0 | B win rate vs A |
|---|---|---|
| `report-extraction` | **0.60** [0.45, 0.74] | 0.40 [0.26, 0.55] |
| `version-drift` | 0.42 [0.29, 0.58] | 0.15 [0.07, 0.29] |
| `traceback-triage` | 0.20 [0.10, 0.35] | 0.20 [0.10, 0.35] |
| `eol-remediation` | 0.16 [0.07, 0.30] | 0.03 [0.00, 0.14] |
| `closure-order` | 0.15 [0.07, 0.30] | 0.26 [0.15, 0.42] |
| `claim-layering` | 0.15 [0.07, 0.29] | 0.30 [0.18, 0.45] |

The contract is preferred on **the one task whose answer shape the prompt specifies** — the same task
where the mechanical check goes from 1–2/20 to 17–20/20 — and is dispreferred everywhere else, most
sharply on `eol-remediation` and the layering tasks where the contract's structure is not asked for. The
gateway baseline (A) is preferred over the contract on five of six tasks, so this is not an artefact of
direct-to-provider access.

Interpretation, stated as narrowly as the data allows: structured interim output is a **format**
intervention that pays off when a consumer needs a shape, and costs judged quality when it does not. The
paper's claim should be "the contract buys compliance, and compliance is worth paying for where the task
defines a shape — not everywhere".

### Replication on a fresh subset, and the validity table

The instrument was re-run on three tasks (238 → 236 presentations, a fresh draw) with the two-order design
kept and an explicit validity flag per judge:

| judge | B win rate | 95 % CI | position bias | valid? |
|---|---|---|---|---|
| GLM-5.3-Flash | 0.342 | [0.262, 0.432] | 0.57 | yes |
| DeepSeek-V3.2 | 0.390 | [0.307, 0.480] | **0.87** | **no** |

The valid judge reproduces the per-task pattern on an independent subset: `report-extraction` 0.59
[0.43, 0.73] against `eol-remediation` 0.13 [0.06, 0.27] and `traceback-triage` 0.30 [0.18, 0.45]. The
invalidated judge sits near 0.4 on all three tasks — the flat profile a position-follower produces, and
exactly why it is excluded rather than averaged.

### The second judge failed the pre-registered check — reported as invalidated, not as confirmation

DeepSeek-V3.2 re-judged the same 238 A0-vs-B presentations. Its aggregate agrees in direction (B wins
0.370 [0.311, 0.433]) but its **position-bias share is 0.836**: it preferred whichever answer was shown
first in 84 % of decisive pairs. The design sets the threshold at 0.60, so this pass is **invalidated**
and its per-task breakdown — which does not reproduce the `report-extraction` reversal — cannot be used
as evidence either way. The two judges agree on 60 % of identical presentations, which is what one expects
when one of them is answering by position.

Recording this matters more than the number: without the pre-registered rule, a 0.370 that "agrees" would
have been written up as a replication.

Threats specific to this instrument: **one valid judge** (GLM-5.3-Flash) for the per-task claim, twenty
pairs per task, answers truncated to 6000 characters for judging, and a DeepSeek judge that must be
re-run with position fully counterbalanced before its verdicts count. The per-task pattern is the claim;
the aggregate is not.

## Threats to validity

1. **Same-family judging.** The primary judge shares a family with the subject; the cross-family judge
   exists because of that and shows how much the choice matters.
2. **Rater variance dominates** the judged outcome at n=20 per cell, so small arm differences cannot be
   separated from judging noise.
3. **One subject model.** Nothing here licenses a claim about other models; replication is E6-style work.
4. **Intercepts are extrapolations** across a narrow character range.
5. **Two cells were short of 20 rows** in the anchored pass (C 18, D 19); means use the rows that exist
   and every table in the paper prints the counts next to the number.

## What this supports

* The contract reliably buys **format compliance** where a shape is checkable (1–2/20 → 17–20/20).
* The contract costs a **fixed per-call latency premium**, not proportional verbosity.
* On judged quality the current instrument **cannot rank the arms**; only A > A0 is stable, and the paper
  states that instead of a leaderboard.
* The contract is preferred exactly where the task specifies a shape (`report-extraction`, 0.60) and
  dispreferred elsewhere (0.03–0.42), so the contribution is conditional on the task, not general.

