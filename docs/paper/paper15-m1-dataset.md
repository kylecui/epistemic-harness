# Paper 1.5 — the M1 dataset: what it contains and how it was made

Frozen at tag `paper-data-freeze-2026-11-26`. Every number below can be recomputed with the scripts in
`experiments/`; nothing here depends on a model's self-report.

## What is in it

600 runs: five arms × six tasks × twenty samples, one subject model, executed on the isolated lab plane
(`docker-compose.lab.yml`, port 8788) so the campaign could not disturb the working router.

| Axis | Values |
|---|---|
| Arm | `A0` direct-to-provider, `A` gateway without the contract, `B`/`C`/`D` three contract variants |
| Task | `traceback-triage`, `version-drift`, `eol-remediation`, `claim-layering`, `report-extraction`, `closure-order` |
| Sample | 20 independent generations per (arm, task) cell |
| Subject | `deepseek-ai/DeepSeek-V4-Flash` (SiliconFlow) |

Each record carries `arm`, `task`, `sample`, `ts`, `elapsed`, `model` (as the upstream reported it),
`text`, `error`, `runner` (execution plane), `gateway` (endpoint used), plus the task's `check` and
`judge_focus`. The `runner` field exists because a run whose plane is unrecorded is not evidence —
`tests/test_experiment_runner_check.py` refuses records without it.

## How each judgement is attached

* **Mechanical**: one regex per task, computed from the answer alone. Deterministic, no model, no rater
  variance. Primary outcome for any cross-arm comparison.
* **Primary judge**: DeepSeek-V3.2, same family as the subject — kept because it was the first judge and
  reported *as* a same-family judge, not as ground truth.
* **Cross-family judge**: GLM-5.3-Flash scores the identical answers, so the difference between judges is
  measured instead of assumed away.
* **Anchored rubric**: both judges re-scored everything with per-item 0/1 examples and a tie-break rule,
  which separates "rubric wording" from "model disagreement".

Judged output sits beside the runs as `<cell>.judged.jsonl`, `.judged-qwen.jsonl` (cross-family) and
`.judged-anchor.jsonl` (anchored). A row without a score is a judge failure — never imputed.

## How it was produced (and the defects fixed before trusting it)

1. `experiments/runner.py` generates one cell; `run_campaign.py --lab --resume` walks the grid. `--resume`
   counts **usable** records and drops failed ones, because an interrupted campaign otherwise reports a
   cell full of connection errors as complete.
2. `experiments/judge.py` scores with the primary or cross-family judge; `--suffix` and `--rubric` pick
   the output stream and the rubric variant.
3. Two instrument defects were fixed *before* the numbers were trusted:
   * the judge was being wrapped in the agent contract, so it answered with a Tier tag instead of JSON;
   * the `version-drift` mechanical check scored 0/100 in every arm because it matched one answer's
     wording — it measured vocabulary, so it was removed rather than loosened.
4. `aggregate.py`, `latency_decomp.py` and `judge_agreement.py` produce every table in Papers 1.5, 2 and
   3 from the frozen files.

## Recompute

```bash
python experiments/aggregate.py                        # per-arm/per-task means, mechanical pass, latency
python experiments/latency_decomp.py                   # intercept vs slope per arm
python experiments/judge_agreement.py judged-qwen      # primary vs cross-family
python experiments/judge_agreement.py judged-anchor    # primary vs anchored cross-family
```

## Known limits

* One subject model; nothing here licenses a claim about other models.
* Twenty samples per cell bounds resolution: an arm difference below roughly 0.1 judged mean sits inside
  the noise, which the agreement analysis quantifies rather than assumes.
* Two cells were short of twenty rows in the anchored pass (C 18, D 19); counts are printed beside every
  mean.
* The judge rubric is the weakest instrument in the chain — κ ≈ 0.10 between families — so the dataset is
  reported mechanical-first and any judged ranking is withheld.

