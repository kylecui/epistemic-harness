/**
 * harness-guard — controller-contract enforcement for the Epistemic Harness.
 *
 * Three enforcement layers (transport-level, no prompt trust required):
 *  1. before_agent_start: appends the compact controller contract to the system prompt of
 *     every user turn (survives missing/stale user-level AGENTS.md).
 *  2. tool_call: blocks LARGE implementation work on non-trivial turns until the turn has
 *     used the orchestrator (run_plan / dispatch_subagent / plan_task). Small local edits
 *     stay zero-friction: <=15 changed lines for edit, <=40 lines for write.
 *     Max 2 blocks per turn; explicit user override phrases bypass entirely.
 *  3. Oscillation detection lives in proxy_gateway/thrashing_guard.py (it sees the raw
 *     thinking stream on every client), NOT here — scanning final prose caused false
 *     positives when discussing the framework itself.
 *
 * Load: auto-discovered from ~/.pi/agent/extensions/harness-guard.js (global, all projects).
 */

const CONTRACT = `## Harness controller contract (transport-enforced)
You are the CONTROLLER. Concrete implementation work belongs to sub-agents:
- Decompose multi-step work with orchestrator.run_plan (parallel waves) or plan_task.
- Delegate implementation/review to mcp dispatch_subagent profiles: explorer / coder / deep / critic.
- Do directly only: reading, answering, classification, and tiny mechanical edits (<10 lines).
Epistemic discipline: keep L1 (axioms) / L2 (evidence) / L3 (heuristics) separated, state L3 scope + counter-examples.
Anti-thrashing: if you catch yourself re-litigating without new evidence, stop and state: confirmed facts, the single unknown, 1-3 next actions.

User override phrases bypass all of the above: "直接做" / "不要派发" / "我自己来" / "bypass" / "skip dispatch".`;

const OVERRIDE = /(直接做|不要派发|不用派发|我自己来|bypass|skip dispatch)/i;
const NONTRIVIAL = /(然后|并且|同时|步骤|先.{0,6}再|实现|重构|排查|修复|设计|部署|迁移|测试|优化|新增|compare|refactor|implement|migrate|debug|design)/i;

export default function (pi) {
  let turnNeedsDispatch = false;
  let dispatchedThisTurn = false;
  let blocksThisTurn = 0;
  let overrideThisTurn = false;

  const NEWLINE = String.fromCharCode(10);
  const countLines = (v) => (typeof v === "string" && v.length ? v.split(NEWLINE).length : 0);
  const isLargeChange = (event) => {
    const input = event.input || {};
    if (String(event.toolName) === "edit") {
      const edits = Array.isArray(input.edits) ? input.edits : [];
      const added = edits.reduce((n, e) => n + countLines(e && e.newText), 0);
      return added > 15;
    }
    // write: whole-file creation/replacement
    return countLines(input.content) > 40;
  };

  const isDispatchCall = (event) => {
    const name = String(event.toolName || "");
    if (/run_plan|dispatch_subagent|plan_task/.test(name)) return true;
    // MCP tools are reached through codemode scripts: scan the script body.
    if (name === "codemode" && event.input && typeof event.input.code === "string") {
      return /(run_plan|dispatch_subagent|plan_task)\s*\(/.test(event.input.code);
    }
    return false;
  };

  pi.on("session_start", async (_event, ctx) => {
    try {
      const res = await fetch("http://127.0.0.1:8787/health");
      if (!res.ok) ctx.ui.notify("harness-guard: gateway unhealthy — sub-agents unavailable", "warn");
    } catch {
      ctx.ui.notify("harness-guard: gateway unreachable (127.0.0.1:8787) — run start_harness", "warn");
    }
  });

  pi.on("before_agent_start", async (event, _ctx) => {
    if (event.messageType !== "user") return undefined;
    const prompt = String(event.prompt || "");
    turnNeedsDispatch = prompt.length > 80 || NONTRIVIAL.test(prompt);
    dispatchedThisTurn = false;
    blocksThisTurn = 0;
    overrideThisTurn = OVERRIDE.test(prompt);

    return { systemPrompt: (event.systemPrompt || "") + "\n\n" + CONTRACT };
  });

  pi.on("tool_call", async (event, ctx) => {
    if (isDispatchCall(event)) {
      dispatchedThisTurn = true;
      return undefined;
    }
    const name = String(event.toolName || "");
    if (name !== "edit" && name !== "write") return undefined;
    if (!turnNeedsDispatch || dispatchedThisTurn || overrideThisTurn) return undefined;
    if (!isLargeChange(event)) return undefined; // small local edits stay zero-friction
    if (blocksThisTurn >= 2) return undefined; // safety valve: never deadlock the user
    blocksThisTurn += 1;
    ctx.ui.notify("harness-guard: implementation work blocked until a sub-agent is dispatched", "warn");
    return {
      block: true,
      reason:
        "Controller contract (transport-enforced): this turn requires a sub-agent. " +
        "Call orchestrator.run_plan (task_text) to decompose and delegate, or dispatch_subagent " +
        "(profile explorer/coder/deep/critic) for the concrete change, then retry. " +
        "User can bypass with an explicit phrase (直接做 / 不要派发 / bypass).",
    };
  });
}
