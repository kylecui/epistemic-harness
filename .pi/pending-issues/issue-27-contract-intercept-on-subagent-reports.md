# Output contract intercept fires on sub-agent reports, which are not user-facing turns

## What happens

A text sub-agent dispatched through `dispatch_subagent` comes back with the gateway's
user-facing output contract already applied. Two reports today ended with:

```
[OUTPUT_CONTRACT_INTERCEPT] 输出契约违规 1 项; 首条: 缺少三段式锚点: Core Conclusion/核心结论, Epistemic Breakdown/认识论分解, Evidence Gaps/证据缺口
```

## Why it matters

- A sub-agent report is machine input for the controller, not a turn shown to a user. The
  three-section rule exists to make user-facing answers auditable; applying it here measures
  the wrong surface.
- It spends output budget on every dispatch and can truncate the content the controller needs.
- It pollutes `traces/contract_violations.jsonl`, making real violations harder to find.

## Reproduction

```
tools.mcp__epistemic_orchestrator__dispatch_subagent({agent_profile: "critic", task_text: "..."})
-> the returned text ends with the OUTPUT_CONTRACT_INTERCEPT block
```

## Fix plan

1. Skip `check_output_structure` for dispatch traffic (the gateway already receives
   `X-Harness-Agent-Id`), while keeping the L3-counter-example and silent-promotion checks,
   which stay meaningful for sub-agent reasoning.
2. Do not skip the interim-schema guard: a report claiming to be an interim record must validate.
3. Record the skip in the trace (`contract_checked: false, reason: sub_agent`) so a missing
   intercept is visible rather than silent.

## Acceptance

- A dispatch returns the sub-agent text with no intercept block appended.
- A user-facing reply that omits the anchors still bounces.
- `traces/contract_violations.jsonl` gains no entries from dispatches; the trace states why.
