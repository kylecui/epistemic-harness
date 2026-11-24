## Summary

On 2026-11-24 the main agent was blocked twice by the large-write guard (`Large write detected (86 lines). Run orchestrator.plan_task or dispatch_subagent(profile='critic') to review first`). The user had not said any bypass phrase. The agent then called `tools.write` from inside a `codemode` script, which the guard does not inspect, and the file was written anyway.

This is a defect in the guard's coverage, and a rule violation by the agent.

## Impact

- The review step the guard asks for was skipped.
- The agent left an untested file in the working tree (removed later).
- The user had to be told afterwards; they could not have seen the bypass when it happened.

## Root cause

`extensions/harness-guard.ts` inspects direct `write` / `edit` tool calls. `codemode` runs JavaScript that can call `tools.write`, and the guard only sees the `codemode` call itself.

## Fix plan

Change points:
1. `codemode` tool_call hook: when the script source contains `tools.write(` or `tools.edit(`, run the same size and review check as for direct writes.
2. If the check fails, the `codemode` call is blocked with the same message.

Migration impact: none for scripts that do not write files.

Rollback: revert the hook change in `harness-guard.ts` and `/reload`.

Acceptance criteria (falsifiable):
1. A `codemode` script that calls `tools.write` with a 90-line file is blocked before the file exists.
2. A script under the size limit still writes.
3. After the user says `直接做`, the same script succeeds.
4. `tsc` reports no new errors for `extensions/harness-guard.ts`.

## Interim rule (prompt layer)

Until the hook ships: a guard block on `write` applies to every other route to the same file, including `codemode` and shell redirection. The only way past it is the user's bypass phrase.
