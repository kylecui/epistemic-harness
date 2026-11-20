/**
 * harness-guard (v0.4.0 — P1-2/P2-1 Low-Friction + Deterministic Exit Gate & Anti-Shirking).
 *
 * Incremental additions over v0.3 (P1-2/P2-1):
 *   1. Tracks whether the current turn actually mutated files (`edit` / `write`);
 *      read-only Q&A and System 0/1 turns incur ZERO exit-gate overhead.
 *   2. On `agent_end`, executes repo-configured `.pi/exit_gate.json` checks +
 *      `git status --porcelain` residue scan (e.g. `debug_*.py`, `*.tmp`, `*.bak`).
 *   3. State-coupled Anti-Shirking Detector: catches buck-passing excuses
 *      ("pre-existing", "unrelated to my changes", "不是我引入的", "原有问题")
 *      ONLY when paired with failing checks or leftover residue files.
 *   4. Anti-Infinite-Loop Circuit Breaker (`max_gate_retries = 3`):
 *      - Repeats of identical error fingerprint inject `[ESCALATE_REASONING: high]` once.
 *      - Exhausting retries stops auto-bouncing and surfaces a clean L2 blocker summary.
 */

import { execSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const CONTRACT = `## Harness Epistemic, Dual-Process & Zero-Residue Contract
- Separate L1 (axioms), L2 (primary evidence), and L3 (heuristics with scope + counter-examples).
- Default to the lowest viable cognitive tier: execute small mechanical edits directly without ceremony.
- Own the Green State: never dismiss a blocking test/build failure as "pre-existing" or "not introduced by my changes"; fix blocking failures in touched/dependent paths and delete all temporary scratch files before finishing.
- User bypass phrases: "直接做" / "不要派发" / "bypass" / "skip exit gate".`;

const OVERRIDE = /(直接做|不要派发|不用派发|我自己来|bypass|skip dispatch)/i;
const EXIT_GATE_BYPASS = /(skip exit gate|跳过验收|先不跑测试)/i;
const LARGE_ARCH_INTENT = /(重构整个|架构迁移|多模块重构|multi-file refactor|migrate architecture|redesign system)/i;

const SHIRKING_PATTERNS: RegExp[] = [
  /\bpre[- ]?existing\b/i,
  /\bunrelated to (?:my|these|our) changes?\b/i,
  /\bnot introduced by\b/i,
  /\bout of scope\b/i,
  /\bleft (?:as an exercise|for (?:the )?user)\b/i,
  /(不是我引入|原有问题|历史遗留|与本次修改无关|超出本次范围|留给用户|非本次改动导致)/,
];

interface ExitGateCheck {
  name: string;
  command: string;
  required?: boolean;
}

interface ExitGateConfig {
  enabled: boolean;
  max_gate_retries: number;
  command_timeout_ms: number;
  checks: ExitGateCheck[];
  residue_globs: string[];
}

const DEFAULT_EXIT_GATE: ExitGateConfig = {
  enabled: true,
  max_gate_retries: 3,
  command_timeout_ms: 60000,
  checks: [],
  residue_globs: ["*.tmp", "*.bak", "*.orig", "debug_*.py", "scratch_*", "tmp_*"],
};

function loadExitGateConfig(cwd: string): ExitGateConfig {
  const cfgPath = join(cwd, ".pi", "exit_gate.json");
  if (!existsSync(cfgPath)) return { ...DEFAULT_EXIT_GATE };
  try {
    const parsed = JSON.parse(readFileSync(cfgPath, "utf-8"));
    return { ...DEFAULT_EXIT_GATE, ...parsed };
  } catch {
    return { ...DEFAULT_EXIT_GATE };
  }
}

function globToRegex(glob: string): RegExp {
  const escaped = glob.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".");
  return new RegExp(`(^|/)${escaped}$`, "i");
}

function scanResidueFiles(cwd: string, residueGlobs: string[]): string[] {
  try {
    const out = execSync("git status --porcelain", { cwd, encoding: "utf-8", timeout: 5000 });
    const matchers = residueGlobs.map(globToRegex);
    const hits: string[] = [];
    for (const rawLine of out.split(/\r?\n/)) {
      if (!rawLine.startsWith("?? ")) continue;
      const relPath = rawLine.slice(3).trim();
      if (matchers.some((rx) => rx.test(relPath))) {
        hits.push(relPath);
      }
    }
    return hits;
  } catch {
    return [];
  }
}

function runCheck(cwd: string, check: ExitGateCheck, timeoutMs: number): { ok: boolean; tail: string } {
  try {
    execSync(check.command, { cwd, encoding: "utf-8", timeout: timeoutMs, stdio: ["ignore", "pipe", "pipe"] });
    return { ok: true, tail: "" };
  } catch (err: any) {
    const combined = `${err?.stdout || ""}\n${err?.stderr || ""}`.trim();
    const lines = combined.split(/\r?\n/).slice(-25).join("\n");
    return { ok: false, tail: lines || String(err?.message || "non-zero exit") };
  }
}

function detectShirkingPhrases(text: string): string[] {
  const hits: string[] = [];
  for (const rx of SHIRKING_PATTERNS) {
    const m = text.match(rx);
    if (m) hits.push(m[0]);
  }
  return hits;
}

function computeErrorFingerprint(failures: Array<{ name: string; tail: string }>, residue: string[]): string {
  const normalized = failures
    .map((f) => `${f.name}:${f.tail.replace(/\d+\.\d+s/g, "X.Xs").slice(-400)}`)
    .concat(residue.map((r) => `residue:${r}`))
    .join("|");
  return createHash("sha1").update(normalized).digest("hex").slice(0, 12);
}

function estimateChangedLines(toolName: string, input: Record<string, any> | undefined): number {
  if (!input) return 0;
  if (toolName === "write") {
    const content = String(input.content || input.text || "");
    return content ? content.split(/\r?\n/).length : 0;
  }
  if (toolName === "edit") {
    const newStr = String(input.new_string || input.newText || input.replacement || "");
    const oldStr = String(input.old_string || input.oldText || "");
    const newLines = newStr ? newStr.split(/\r?\n/).length : 0;
    const oldLines = oldStr ? oldStr.split(/\r?\n/).length : 0;
    return Math.max(newLines, oldLines);
  }
  return 0;
}

function extractLastAssistantText(event: any): string {
  const messages = Array.isArray(event?.messages) ? event.messages : [];
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    if (msg?.role !== "assistant") continue;
    if (typeof msg.content === "string") return msg.content;
    if (Array.isArray(msg.content)) {
      return msg.content
        .filter((b: any) => b?.type === "text" && typeof b?.text === "string")
        .map((b: any) => b.text)
        .join("\n");
    }
  }
  return String(event?.finalText || "");
}

export default function (pi: any) {
  let isLargeArchTurn = false;
  let dispatchedThisTurn = false;
  let blocksThisTurn = 0;
  let overrideThisTurn = false;
  let bypassExitGateThisTurn = false;

  // Exit Gate & Anti-Shirking state
  let mutatedThisTurn = false;
  let gateRetriesThisTurn = 0;
  let lastErrorFingerprint = "";

  const isDispatchCall = (event: any): boolean => {
    const name = String(event.toolName || "");
    if (/run_plan|dispatch_subagent|plan_task/.test(name)) return true;
    if (name === "codemode" && event.input && typeof event.input.code === "string") {
      return /(run_plan|dispatch_subagent|plan_task)\s*\(/.test(event.input.code);
    }
    return false;
  };

  pi.on("session_start", async (_event: any, ctx: any) => {
    try {
      const res = await fetch("http://127.0.0.1:8787/health");
      if (!res.ok) ctx.ui.notify("harness-guard: gateway unhealthy (127.0.0.1:8787)", "warn");
    } catch {
      ctx.ui.notify("harness-guard: gateway unreachable (127.0.0.1:8787) - run start_harness", "warn");
    }
  });

  pi.on("before_agent_start", async (event: any) => {
    if (event.messageType !== "user") return undefined;
    const prompt = String(event.prompt || "");
    // Preserve Exit Gate retry counters when the continuation turn was injected by our own gate
    const isGateBounce = prompt.startsWith("[HARNESS_EXIT_GATE_RETRY]");
    if (!isGateBounce) {
      isLargeArchTurn = LARGE_ARCH_INTENT.test(prompt);
      dispatchedThisTurn = false;
      blocksThisTurn = 0;
      overrideThisTurn = OVERRIDE.test(prompt);
      bypassExitGateThisTurn = EXIT_GATE_BYPASS.test(prompt);
      mutatedThisTurn = false;
      gateRetriesThisTurn = 0;
      lastErrorFingerprint = "";
    }
    return { systemPrompt: (event.systemPrompt || "") + "\n\n" + CONTRACT };
  });

  pi.on("tool_call", async (event: any, ctx: any) => {
    if (isDispatchCall(event)) {
      dispatchedThisTurn = true;
      return undefined;
    }
    const name = String(event.toolName || "");
    if (name !== "edit" && name !== "write") return undefined;

    mutatedThisTurn = true;

    if (dispatchedThisTurn || overrideThisTurn || blocksThisTurn >= 1) return undefined;

    // P1-2 fix: inspect actual edit/write size; small mechanical edits pass with zero friction!
    const lines = estimateChangedLines(name, event.input);
    const exceedsThreshold = (name === "edit" && lines > 15) || (name === "write" && lines > 40);
    if (!isLargeArchTurn && !exceedsThreshold) return undefined;

    blocksThisTurn += 1;
    ctx.ui.notify(`harness-guard: large ${name} (${lines} lines) — consider plan/critic review first`, "warn");
    return {
      block: true,
      reason:
        `Large ${name} detected (${lines} lines). Run orchestrator.plan_task or dispatch_subagent(profile='critic') ` +
        `to review architectural impact first, or retry directly if already validated (user can say '直接做' / 'bypass').`,
    };
  });

  // Deterministic Exit Gate + State-Coupled Anti-Shirking Guard
  pi.on("agent_end", async (event: any, ctx: any) => {
    if (!mutatedThisTurn || bypassExitGateThisTurn) return undefined;

    const cwd = String(ctx?.cwd || process.cwd());
    const cfg = loadExitGateConfig(cwd);
    if (!cfg.enabled) return undefined;

    const failures: Array<{ name: string; tail: string }> = [];
    for (const check of cfg.checks) {
      const res = runCheck(cwd, check, cfg.command_timeout_ms);
      if (!res.ok && check.required !== false) {
        failures.push({ name: check.name, tail: res.tail });
      }
    }
    const residue = scanResidueFiles(cwd, cfg.residue_globs);

    if (failures.length === 0 && residue.length === 0) {
      gateRetriesThisTurn = 0;
      lastErrorFingerprint = "";
      return undefined;
    }

    const fingerprint = computeErrorFingerprint(failures, residue);
    const repeatedSameError = fingerprint === lastErrorFingerprint;
    lastErrorFingerprint = fingerprint;

    const lastText = extractLastAssistantText(event);
    const shirkingHits = detectShirkingPhrases(lastText);

    if (gateRetriesThisTurn >= cfg.max_gate_retries) {
      ctx.ui.notify(
        `harness-guard: Exit Gate exhausted (${cfg.max_gate_retries} retries, fp=${fingerprint}). Handing L2 blocker to user.`,
        "warn",
      );
      return undefined;
    }

    gateRetriesThisTurn += 1;
    const escalationTag = repeatedSameError ? "\n[ESCALATE_REASONING: high] Identical failure repeated; re-analyze root cause from first principles." : "";
    const shirkingWarning =
      shirkingHits.length > 0
        ? `\n[ANTI_SHIRKING_INTERCEPT] Detected buck-passing phrasing (${shirkingHits.join(", ")}) while verification is still red. Do NOT dismiss blocking failures as "pre-existing" or "unrelated"; fix them now.`
        : "";
    const failureBlock = failures.map((f) => `### Failed Check: ${f.name}\n\`\`\`\n${f.tail}\n\`\`\``).join("\n\n");
    const residueBlock = residue.length > 0 ? `\n### Leftover Residue Files (delete before finishing)\n- ${residue.join("\n- ")}` : "";

    const bouncePrompt =
      `[HARNESS_EXIT_GATE_RETRY] Attempt ${gateRetriesThisTurn}/${cfg.max_gate_retries} (fingerprint=${fingerprint}).\n` +
      `Your turn cannot finish because deterministic Exit Gate verification failed.${shirkingWarning}${escalationTag}\n\n` +
      `${failureBlock}${residueBlock}\n\n` +
      `Fix every blocking failure and remove all residue files, then re-verify until green.`;

    ctx.ui.notify(
      `harness-guard: Exit Gate blocked end_turn (${failures.length} failed check(s), ${residue.length} residue file(s)) — retry ${gateRetriesThisTurn}/${cfg.max_gate_retries}`,
      "warn",
    );

    if (typeof pi.sendUserMessage === "function") {
      pi.sendUserMessage(bouncePrompt, { deliverAs: "followUp" });
    }
    return { continueWith: bouncePrompt };
  });
}
