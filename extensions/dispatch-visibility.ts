/**
 * dispatch-visibility — make sub-agent dispatches visible in the TUI.
 *
 * Before this extension, dispatches (MCP dispatch_subagent / dispatch_readonly /
 * dispatch_tooled) ran silently: the user saw nothing until the final answer.
 * Now every dispatch:
 *   - sets a footer status ("agents: 2 running") while in flight,
 *   - notifies on start (profile, task id) and completion (elapsed, status),
 *   - keeps a rolling in-memory log exposed via /agents,
 *   - mirrors entries to .pi/agent_visibility.jsonl for out-of-band inspection.
 *
 * Read-only observer: it never blocks or modifies tool calls or results.
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { appendFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";

interface DispatchInfo {
  id: string;
  tool: string;
  agent: string;
  taskId: string;
  startedAt: number;
  endedAt?: number;
  ok?: boolean;
}

const DISPATCH_RE = /dispatch_subagent|dispatch_readonly|dispatch_tooled/;
const inFlight = new Map<string, DispatchInfo>();
const history: DispatchInfo[] = [];

function logPath(): string {
  return join(process.cwd(), ".pi", "agent_visibility.jsonl");
}

function record(entry: DispatchInfo, event: "start" | "end"): void {
  try {
    mkdirSync(dirname(logPath()), { recursive: true });
    appendFileSync(logPath(), JSON.stringify({ ts: new Date().toISOString(), event, ...entry }) + "\n");
  } catch {
    /* visibility must never break the turn */
  }
}

function summarize(toolName: string, taskInput: unknown): { agent: string; taskId: string } {
  const input = (taskInput ?? {}) as Record<string, unknown>;
  // Profile can come from args (orchestrator tools) or from the tool name itself
  // (dispatch_readonly -> explorer-ro, dispatch_tooled -> coder).
  const byTool: Record<string, string> = {
    dispatch_subagent: "auto(subagent)",
    dispatch_readonly: "explorer-ro",
    dispatch_tooled: "coder(tooled)",
  };
  const explicit = input.agent_profile ?? input.profile;
  const agent = String(explicit ?? byTool[toolName] ?? "auto");
  const taskId = String(input.task_id ?? "-");
  return { agent, taskId };
}

export default function (pi: ExtensionAPI) {
  pi.on("tool_call", async (event: any, ctx: any) => {
    const name = String(event?.toolName ?? "");
    if (!DISPATCH_RE.test(name)) return undefined;
    const id = String(event?.toolCallId ?? `${Date.now()}`);
    const { agent, taskId } = summarize(name, event?.input);
    const info: DispatchInfo = { id, tool: name, agent, taskId, startedAt: Date.now() };
    inFlight.set(id, info);
    history.push(info);
    if (history.length > 50) history.shift();
    record(info, "start");
    try {
      ctx.ui?.setStatus?.("agents", `agents: ${inFlight.size} running`);
      ctx.ui?.notify?.(`▶ dispatch ${agent} (task=${taskId})`, "info");
      ctx.ui?.setWorkingMessage?.(`子代理 ${agent} 运行中（task=${taskId}）…`);
    } catch {
      /* noop */
    }
    return undefined;
  });

  pi.on("tool_execution_end", async (event: any, ctx: any) => {
    const id = String(event?.toolCallId ?? "");
    const info = inFlight.get(id);
    if (!info) return undefined;
    inFlight.delete(id);
    info.endedAt = Date.now();
    info.ok = !event?.isError;
    const secs = ((info.endedAt - info.startedAt) / 1000).toFixed(1);
    record(info, "end");
    try {
      // Keep a persistent summary in the footer instead of clearing to undefined:
      // a completed dispatch stays glanceable until the next one starts.
      ctx.ui?.setStatus?.("agents", inFlight.size > 0
        ? `agents: ${inFlight.size} running`
        : `agents: last ${info.ok ? "ok" : "FAIL"} ${info.agent} ${secs}s`);
      ctx.ui?.setWorkingMessage?.();
      ctx.ui?.notify?.(
        `${info.ok ? "✔" : "✖"} dispatch ${info.agent} done in ${secs}s (task=${info.taskId})`,
        info.ok ? "info" : "warn",
      );
    } catch {
      /* noop */
    }
    return undefined;
  });

  pi.registerCommand("agents", {
    description: "Show recent sub-agent dispatches (state, elapsed, task id)",
    handler: async (_args: string, ctx: any) => {
      const rows = history.slice(-12).map((d) => {
        const state = d.endedAt ? (d.ok ? "ok" : "FAIL") : "running";
        const secs = d.endedAt ? `${((d.endedAt - d.startedAt) / 1000).toFixed(1)}s` : "-";
        return `${state.padEnd(7)} ${d.agent.padEnd(10)} task=${String(d.taskId).padEnd(16)} ${secs}`;
      });
      ctx.ui?.notify?.(rows.length ? `recent dispatches:\n${rows.join("\n")}` : "no dispatches this session", "info");
    },
  });
}
