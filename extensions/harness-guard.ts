/**
 * harness-guard — controller-contract enforcement for the Epistemic Harness.
 *
 * Three enforcement layers (transport-level, no prompt trust required):
 *  1. before_agent_start: appends the compact controller contract to the system prompt of
 *     every user turn (survives missing/stale user-level AGENTS.md).
 *  2. tool_call: blocks concrete implementation work (edit/write) on non-trivial turns
 *     until the turn has used the orchestrator (run_plan / dispatch_subagent / plan_task).
 *     Max 2 blocks per turn, and explicit user override phrases bypass entirely.
 *  3. message_end: detects reasoning oscillation in assistant output (Wait, but ... /
 *     等等不对 ...) and injects a stop-loss directive into the next turn's system prompt.
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

const OSCILLATION = /(wait,?\s*but|等等不对|话又说回来|let me reconsider|on second thought)/gi;
const OVERRIDE = /(直接做|不要派发|不用派发|我自己来|bypass|skip dispatch)/i;
const NONTRIVIAL = /(然后|并且|同时|步骤|先.{0,6}再|实现|重构|排查|修复|设计|部署|迁移|测试|优化|新增|compare|refactor|implement|migrate|debug|design)/i;

export default function (pi) {
  let turnNeedsDispatch = false;
  let dispatchedThisTurn = false;
  let blocksThisTurn = 0;
  let overrideThisTurn = false;
  let pendingStopLoss = false;
  let oscillatedThisTurn = 0;

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
    oscillatedThisTurn = 0;

    let extra = CONTRACT;
    if (pendingStopLoss) {
      extra += `\n\n## Previous turn triggered the oscillation guard
State only: (1) confirmed L1/L2 facts, (2) the single minimal unknown, (3) 1-3 concrete next actions. Do not resume the previous debate.`;
      pendingStopLoss = false;
    }
    return { systemPrompt: (event.systemPrompt || "") + "\n\n" + extra };
  });

  pi.on("tool_call", async (event, ctx) => {
    if (isDispatchCall(event)) {
      dispatchedThisTurn = true;
      return undefined;
    }
    const name = String(event.toolName || "");
    if (name !== "edit" && name !== "write") return undefined;
    if (!turnNeedsDispatch || dispatchedThisTurn || overrideThisTurn) return undefined;
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

  pi.on("message_end", async (event, _ctx) => {
    if (!event.message || event.message.role !== "assistant") return undefined;
    const text = extractText(event.message);
    if (!text) return undefined;
    const hits = text.match(OSCILLATION) || [];
    if (hits.length >= 2) {
      oscillatedThisTurn += 1;
      pendingStopLoss = true;
    }
    return undefined;
  });

  function extractText(message) {
    const parts = message.content ?? [];
    if (typeof parts === "string") return parts;
    if (!Array.isArray(parts)) return "";
    return parts
      .map((p) => (typeof p === "string" ? p : p && p.type === "text" ? String(p.text || "") : ""))
      .join("\n");
  }
}
