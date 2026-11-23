# A0/A/B/C/D Experiment Platform

Campaign for Paper 2/3 and Paper 1.5 §8. One unit = one (arm, task, sample) transcript in `runs/`.

## Arms (governance surface is the ONLY variable)

| Arm | Endpoint | System prompt | Extra |
|---|---|---|---|
| A0 | direct provider API (kimi/zhipu) | vanilla | zero governance; judged post-hoc |
| A | gateway 127.0.0.1:8787 | vanilla | routing/quota only; interim guard off |
| B | gateway | + SubagentReport JSON protocol | gateway attaches/validates report (opt-in header) |
| C | gateway | + layer discipline instructions | B + reasoning-ledger closure at submit time |
| D | gateway | same as C | `response_format=json_object` where provider supports |

## Tasks

`fixtures/tasks.yaml` — six replayables (three derived from this repo's real
incidents: traceback-triage, version-drift, eol-remediation; three synthetic:
claim-layering, report-extraction, closure-order). Each has a mechanical
`regex_all` check and a `judge_focus`.

## Run

```bash
python experiments/runner.py --arm B --task traceback-triage --samples 20
python experiments/runner.py --arm A0 --task version-drift --samples 20 --provider kimi
python experiments/judge.py --arm A0 --task version-drift   # adds LLM-judge scores
```

Judge calls the gateway on the critic tier (blind to the arm). Mechanical
checks are arm-independent; structured arms (B/C/D) additionally admit
machine validation via contracts/schemas.

## Metrics (aggregated across samples, per arm×task)

- mechanical pass rate; judge item means (correct / no_unsupported_claims /
  no_overclaim / layers_disciplined / focus)
- stability: pairwise text similarity across the arm's N samples
- cost: prompt/completion tokens per run (from gateway traces / direct responses)

## Known limitations (to state in the paper)

- A0 approximates "vanilla pi" by a direct API call with a plain system prompt;
  the pi-CLI nuance (tooling defaults) is out of scope for this campaign.
- N=20 per cell is the default; power analysis deferred to first results.
- Judge and subject may share provider families; critic-tier cross-family
  routing mitigates but does not eliminate this.
