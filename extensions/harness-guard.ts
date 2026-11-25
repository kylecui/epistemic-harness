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
 *   5. v0.4.1 (issue #2 / loop memory):
 *      - `verdict` is explicit: green only when at least one check actually ran;
 *        zero configured checks yields `no_evidence` (blocking only under
 *        `evidence_policy: enforce`, otherwise a warning).
 *      - `.pi/loop_ledger.jsonl` persists every gate outcome so the same failure
 *        fingerprint escalating across turns is visible, not just within one turn.
 */

import { execSync, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

const AUDIT_LOG = join(homedir(), ".pi", "agent", "harness-guard.log");
function audit(line: string): void {
  try {
    mkdirSync(dirname(AUDIT_LOG), { recursive: true });
    appendFileSync(AUDIT_LOG, `${new Date().toISOString()} ${line}` + String.fromCharCode(10));
  } catch {
    /* logging must never break the session */
  }
}

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
  evidence_policy?: "off" | "warn" | "enforce";
}

const UNIVERSAL_GATE = join(homedir(), ".pi", "harness", "scripts", "gate_universal.py");

function defaultChecks(): ExitGateCheck[] {
  // Only when the global harness install is present: a missing script would fail every turn.
  if (!existsSync(UNIVERSAL_GATE)) return [];
  return [{ name: "universal", command: `python "${UNIVERSAL_GATE}"`, required: true }];
}

function orchestratorToolsAvailable(): boolean {
  // Issue #16: never suggest an action the session cannot take. The orchestrator MCP server is what
  // exposes plan_task / dispatch_subagent, so its absence in mcp.json means the suggestion is a lie.
  const candidates = [join(homedir(), ".pi", "agent", "mcp.json"), join(process.cwd(), ".pi", "mcp.json")];
  for (const file of candidates) {
    try {
      if (readFileSync(file, "utf8").toLowerCase().includes("orchestrator")) return true;
    } catch {
      // absent config is the common case, not an error
    }
  }
  return false;
}

function writeRemediation(what: string, lines: number): string {
  if (orchestratorToolsAvailable()) {
    return `Large ${what} detected (${lines} lines). Run orchestrator.plan_task or ` +
      `dispatch_subagent(profile='critic') to review architectural impact first, or retry directly ` +
      `if already validated (user can say '直接做' / 'bypass').`;
  }
  return `Large ${what} detected (${lines} lines), and no planning tool is connected in this session — ` +
    `split it into smaller files instead of working around the guard with a shell heredoc, or ask the ` +
    `user to approve ('直接做').`;
}

function scanCodemodeWrites(code: string): { calls: number; literalLines: number; computed: boolean } {
  // Issue #19: codemode can call tools.write/tools.edit, which the guard never saw. Scan the script
  // for those calls, measure a LITERAL payload, and report when the payload is computed (unknown size).
  const call = /tools\.(?:write|edit)\s*\(/g;
  let calls = 0;
  let literalLines = 0;
  let computed = false;
  let match: RegExpExecArray | null;
  while ((match = call.exec(code)) !== null) {
    calls += 1;
    const body = code.slice(match.index + match[0].length, match.index + match[0].length + 40000);
    const key = /(?:content|newText|text)\s*:\s*/.exec(body);
    if (!key) { computed = true; continue; }
    const rest = body.slice(key.index + key[0].length).trimStart();
    const quote = rest[0];
    if (quote !== '"' && quote !== "'" && quote !== "`") { computed = true; continue; }
    let literal = "";
    for (let i = 1; i < rest.length; i += 1) {
      const ch = rest[i];
      if (ch === "\\") { literal += rest[i + 1] ?? ""; i += 1; continue; }
      if (ch === quote) break;
      literal += ch;
    }
    literalLines = Math.max(literalLines, literal.split("\n").length);
  }
  return { calls, literalLines, computed };
}

const DEFAULT_EXIT_GATE: ExitGateConfig = {
  enabled: true,
  max_gate_retries: 3,
  command_timeout_ms: 60000,
  // A project that declares no gate still gets the cheap, language-agnostic invariants: scratch files,
  // CRLF committed into .sh/.py, a credential written into a tracked file. Running an unknown project's
  // own tests is deliberately NOT attempted (toolchain, duration, side effects).
  checks: defaultChecks(),
  residue_globs: ["*.tmp", "*.bak", "*.orig", "debug_*.py", "scratch_*", "tmp_*"],
  evidence_policy: "warn",
};

function loadExitGateConfig(cwd: string): ExitGateConfig {  const cfgPath = join(cwd, ".pi", "exit_gate.json");
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
    // Keep the test-identity header lines (FAIL:/ERROR:) even when the 25-line
    // tail window cuts them off (issue #8): a bounce without the failing test
    // name costs extra gate round-trips before the fix is even identifiable.
    const all = combined.split(/\r?\n/);
    const tailLines = all.slice(-25);
    const inTail = new Set(tailLines);
    const headers = all.filter((l) => /^(FAIL|ERROR): /.test(l) && !inTail.has(l));
    const lines = [...headers, ...tailLines].join("\n");
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

// Cross-turn loop memory: the per-turn retry counter resets on every new user
// message, so the same failure could bounce forever without ever escalating.
const LEDGER_REL = join(".pi", "loop_ledger.jsonl");

function readLedger(cwd: string): Array<Record<string, any>> {
  const path = join(cwd, LEDGER_REL);
  if (!existsSync(path)) return [];
  try {
    return readFileSync(path, "utf-8")
      .split(/\r?\n/)
      .filter((l) => l.trim())
      .map((l) => {
        try {
          return JSON.parse(l);
        } catch {
          return null;
        }
      })
      .filter((r): r is Record<string, any> => r !== null);
  } catch {
    return [];
  }
}

function appendLedger(cwd: string, record: Record<string, any>): void {
  try {
    const path = join(cwd, LEDGER_REL);
    mkdirSync(dirname(path), { recursive: true });
    appendFileSync(path, JSON.stringify({ ...record, ts: new Date().toISOString() }) + String.fromCharCode(10));
  } catch {
    /* the ledger must never break the gate */
  }
}

function countLedgerRepeats(cwd: string, fingerprint: string): number {
  return readLedger(cwd).filter((r) => r.fingerprint === fingerprint && r.verdict !== "green").length;
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

function runReviewCheck(cwd: string, text: string): any | null {
  // Judge the assistant text with the Python review contract. Tries python
  // interpreters in order; returns null when unavailable (never breaks a turn).
  const script = join(cwd, "orchestrator", "exit_gate.py");
  if (!existsSync(script)) return null;
  for (const py of ["python", "py", "python3"]) {
    try {
      const res = spawnSync(py, [script, "--review-check"], {
        cwd, input: text, encoding: "utf-8", timeout: 30000,
        stdio: ["pipe", "pipe", "pipe"],
      });
      if (res.status === 0 && res.stdout) return JSON.parse(String(res.stdout).trim());
    } catch { /* try next interpreter */ }
  }
  return null;
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
  let codemodeWarned = false;
  let bypassExitGateThisTurn = false;

  // Exit Gate & Anti-Shirking state
  let mutatedThisTurn = false;
  let gateRetriesThisTurn = 0;
  // Review-contract self-loop state (2026-11-22): bounces once, then halts.
  let reviewRetriesThisTurn = 0;
  let lastErrorFingerprint = "";

  const isDispatchCall = (event: any): boolean => {
    const name = String(event.toolName || "");
    if (/run_plan|dispatch_subagent|plan_task/.test(name)) return true;
    if (name === "codemode" && event.input && typeof event.input.code === "string") {
      return /(run_plan|dispatch_subagent|plan_task)\s*\(/.test(event.input.code);
    }
    return false;
  };

  // ---- global install resolution (2026-11-23): the harness must work from
  // ANY working directory. Global assets resolve HARNESS_HOME (env) or the
  // default global install ~/.pi/harness; development sessions fall back to
  // the current repo. PROJECT files (.pi/exit_gate.json, task_contract,
  // traces) stay cwd-relative BY DESIGN — they are per-project state.
  const HARNESS_HOME = process.env.HARNESS_HOME || join(homedir(), ".pi", "harness");
  const harnessFile = (...segments: string[]): string | null => {
    const globalPath = join(HARNESS_HOME, ...segments);
    if (existsSync(globalPath)) return globalPath;
    const devPath = join(process.cwd(), ...segments);
    if (existsSync(devPath)) return devPath;
    return null;
  };

  // Persistent footer status with the loaded contract version
  // (2026-11-23): transient notify only lasts a moment; pilots want the
  // version glanceable at all times. Source of truth: the gateway's /version
  // endpoint — it answers from the repo that BUILT the running container, so
  // it is correct even in global mode where the client's cwd is not the
  // harness repo (cwd AGENTS.md parsing fails there). Falls back to the
  // cwd parse when the gateway is unreachable.
  const setVersionFooter = (ctx: any) => {
    const applyLocal = () => {
      try {
        // Global mode: version from the installed HARNESS_HOME (or dev repo),
        // never from the client's cwd — the cwd project is not the harness.
        const agentsPath = harnessFile("AGENTS.md");
        if (!agentsPath) return;
        const agentsText = readFileSync(agentsPath, "utf-8");
        const loadedM = agentsText.match(/epistemic-dual-process-harness \(v(\d+\.\d+\.\d+)\)/);
        if (loadedM) {
          ctx.ui?.setStatus?.("harness", `harness v${loadedM[1]}`);
          audit(`[footer] setStatus harness v${loadedM[1]} (from ${agentsPath})`);
        } else {
          audit("[footer] AGENTS.md found but no version header");
        }
      } catch (e) {
        audit(`[footer] local fallback failed: ${e}`);
      }
    };
    try {
      fetch("http://127.0.0.1:8787/version")
        .then(async (res) => {
          if (!res.ok) { applyLocal(); return; }
          const data = await res.json().catch(() => null);
          const v = data?.loaded_contract_version || data?.spec_version;
          if (v) ctx.ui?.setStatus?.("harness", `harness v${v}`);
          else applyLocal();
        })
        .catch(() => applyLocal());
    } catch { applyLocal(); }
  };

  // ---- version banner + gateway health (2026-11-23). pi 1.6.0's TUI runtime
  // never dispatches "session_start" to extension handlers (verified in the
  // installed bundle: _emitExtensionEvent covers agent_start/agent_end/
  // turn_*/message_*/tool_execution_* only), so the earliest reachable moment
  // is the first user turn. Banner text comes from the tested python CLI
  // (release notes shown once per version); the health check below was
  // previously hooked to session_start and therefore never ran.
  let bannerShown = false;
  const showVersionBanner = (ctx: any) => {
    if (bannerShown) return;
    bannerShown = true;
    try {
      const script = harnessFile("scripts", "harness_version.py");
      if (script) {
        const cwd = String(ctx?.cwd || process.cwd());
        for (const py of ["python", "py", "python3"]) {
          try {
            const res = spawnSync(py, [script, "--banner"], {
              cwd: dirname(script), encoding: "utf-8", timeout: 30000, stdio: ["ignore", "pipe", "pipe"],
            });
            if (res.status === 0 && res.stdout) {
              for (const ln of String(res.stdout).split(/\r?\n/).filter((l: string) => l.trim())) {
                ctx.ui?.notify(ln, ln.includes("DRIFT") ? "warn" : "info");
              }
              audit(`[banner] shown via ${py}`);
              break;
            }
            audit(`[banner] ${py} unavailable (status=${res.status})`);
          } catch (e) {
            audit(`[banner] ${py} failed: ${e}`);
          }
        }
      }
      if (!bannerShown) { /* unreachable */ }
    } catch (e) {
      audit(`[banner] python path failed: ${e}`);
    }
    // TS fallback: minimal banner (no release notes) if no python answered
    try {
      const agentsPath = harnessFile("AGENTS.md");
      if (!agentsPath) { audit("[banner] no AGENTS.md in HARNESS_HOME or repo"); return; }
      const agentsText = readFileSync(agentsPath, "utf-8");
      const loadedM = agentsText.match(/epistemic-dual-process-harness \(v(\d+\.\d+\.\d+)\)/);
      if (loadedM) {
        ctx.ui?.notify(`[harness] contract v${loadedM[1]} loaded (release notes need python on PATH)`, "info");
        audit("[banner] fallback shown");
      }
    } catch (e) {
      audit(`[banner] fallback failed: ${e}`);
    }
    // gateway health (moved from the dead session_start hook)
    try {
      fetch("http://127.0.0.1:8787/health").then((res) => {
        if (!res.ok) ctx.ui?.notify("harness-guard: gateway unhealthy (127.0.0.1:8787)", "warn");
      }).catch(() => {
        ctx.ui?.notify("harness-guard: gateway unreachable (127.0.0.1:8787) - run start_harness", "warn");
      });
    } catch { /* health check must never break the turn */ }
  };

  pi.on("before_agent_start", async (event: any, ctx: any) => {
    if (event.messageType !== "user") return undefined;
    showVersionBanner(ctx);
    setVersionFooter(ctx);
    const prompt = String(event.prompt || "");
    // Preserve retry counters when the continuation turn was injected by our own gate
    const isGateBounce = prompt.startsWith("[HARNESS_EXIT_GATE_RETRY]") || prompt.startsWith("[HARNESS_REVIEW_GATE_RETRY]");
    if (!isGateBounce) {
      isLargeArchTurn = LARGE_ARCH_INTENT.test(prompt);
      dispatchedThisTurn = false;
      blocksThisTurn = 0;
      overrideThisTurn = OVERRIDE.test(prompt);
      bypassExitGateThisTurn = EXIT_GATE_BYPASS.test(prompt);
      mutatedThisTurn = false;
      gateRetriesThisTurn = 0;
      reviewRetriesThisTurn = 0;
      lastErrorFingerprint = "";
    }
    return { systemPrompt: (event.systemPrompt || "") + "\n\n" + CONTRACT };
  });

  const MUTATING_BASH = /(>>?\s*\S|tee|mv|cp|sed\s+-i|rm|mkdir|git\s+(add|commit|checkout|reset|restore)|open\([^)]*['\"]w|write_text\(|Path\([^)]*\)\.write)/;
  const isMutatingBash = (input: any) => {
    const cmd = typeof input?.command === "string" ? input.command : "";
    return MUTATING_BASH.test(cmd);
  };

  // ---- sub-agent visibility: every dispatch is announced with profile, model, tier, effort ----
  const hookAgent = (ctx: any, label: string, taskId: string, profile: string) => {
    const msg = `[sub-agent] start ${label} id=${taskId} profile=${profile}`;
    ctx.ui.notify(msg, "info");
    audit(msg);
  };
  const finishAgent = (ctx: any, label: string, text: string) => {
    const collect = (obj: any, out: any[] = []): any[] => {
      if (Array.isArray(obj)) { obj.forEach((x) => collect(x, out)); return out; }
      if (obj && typeof obj === "object") {
        if (typeof obj.selected_model === "string") out.push(obj);
        Object.values(obj).forEach((v) => collect(v, out));
        return out;
      }
      return out;
    };
    const emitDone = (m: any) => {
      const msg = `[sub-agent] done ${label} model=${m.selected_model || "?"} tier=${m.routed_tier || "?"} effort=${m.effort || "-"}`;
      ctx.ui.notify(msg, "info");
      audit(msg);
    };
    const emitUnknown = () => {
      // A dispatch that ran inside a codemode script returns the script's own output, not the
      // MCP payload, so the model metadata is simply not in the text we can see.
      const msg = label === "tool=codemode"
        ? `[sub-agent] done ${label} (dispatch ran inside a codemode script: model metadata not in its output)`
        : `[sub-agent] done ${label} (no model metadata in result)`;
      ctx.ui.notify(msg, "info");
      audit(msg);
    };

    if (process.env.HARNESS_GUARD_DEBUG) audit(`[debug] result head: ${text.slice(0, 400)}`);
    let parsed: any = null;
    const tryParse = (candidate: string) => {
      try { return JSON.parse(candidate); } catch { return null; }
    };
    // 1) direct tool results are clean JSON; 2) codemode wraps output after "Output:";
    // 3) fall back to unescaping the whole text.
    parsed = tryParse(text);
    if (parsed === null) {
      const outIdx = text.indexOf("Output:");
      if (outIdx >= 0) parsed = tryParse(text.slice(outIdx + "Output:".length).trim());
    }
    if (parsed === null) parsed = tryParse(text.replace(/\\"/g, '"'));
    if (process.env.HARNESS_GUARD_DEBUG) audit(`[debug] parsed=${parsed !== null} len=${text.length}`);
    if (parsed !== null) {
      const found = collect(parsed);
      if (process.env.HARNESS_GUARD_DEBUG) audit(`[debug] collect found=${found.length} keys=${parsed && typeof parsed === "object" ? Object.keys(parsed).join("|") : typeof parsed}`);
      if (found.length) { found.forEach(emitDone); return; }
    }
    const norm = text.replace(/\\"/g, '"');
    const re = /"selected_model":\s*"([^"]*)"[[\s\S]{0,200}?"routed_tier":\s*"([^"]*)"[[\s\S]{0,120}?"effort":\s*"([^"]*)"/g;
    const rows = [...norm.matchAll(re)];
    if (!rows.length) { emitUnknown(); return; }
    for (const m of rows) {
      emitDone({ selected_model: m[1], routed_tier: m[2], effort: m[3] });
    }
  };

  // (the version banner moved to showVersionBanner above, called from
  // before_agent_start — the earliest UI-reachable moment in pi 1.6.0)

  // ---- controller metrics (P2.9, 2026-11-22): the controller contract is
  // enforced by thresholds above; these records let us MEASURE how the main
  // agent actually works — direct writes vs dispatches per turn — instead of
  // claiming a dispatch rate nobody verified. Append-only, best-effort.
  const metric = (rec: Record<string, unknown>) => {
    try {
      const dir = join(process.cwd(), ".pi");
      if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
      appendFileSync(
        join(dir, "controller_metrics.jsonl"),
        JSON.stringify({ ts: new Date().toISOString(), ...rec }) + "\n"
      );
    } catch { /* metrics must never break a turn */ }
  };

  pi.on("tool_call", async (event: any, ctx: any) => {
    if (process.env.HARNESS_GUARD_DEBUG) {
      const keys = Object.keys(event.input || {}).join(",");
      audit(`[debug] tool_call name=${event.toolName} inputKeys=${keys}`);
    }
    if (isDispatchCall(event)) {
      const code = typeof event.input?.code === "string" ? event.input.code : "";
      const profile = (code.match(/agent_profile["']?\s*[:=]\s*["']([a-z_]+)["']/) || [])[1] || "auto";
      const id = (code.match(/task_id["']?\s*[:=]\s*["']([^"']+)["']/) || [])[1] || "-";
      hookAgent(ctx, String(event.toolName || "dispatch"), id, profile);
    }
    if (isDispatchCall(event)) {
      dispatchedThisTurn = true;
      metric({ event: "dispatch", tool: String(event.toolName || "dispatch") });
      return undefined;
    }
    const name = String(event.toolName || "");
    // HOST-LIFE GUARD (2026-11-24 incident): an agent once force-killed Docker
    // Desktop and edited its global settings-store.json while running, wedging
    // WSL integration (WSAETIMEDOUT) and taking down the ONLY-EXIT router for
    // every session. Engine/lifecycle operations are human-only now: the guard
    // blocks them mechanically and tells the human to run the recovery in a
    // normal terminal. This is not a style rule — it is the anti-recurrence fix.
    if (name === "bash" || name === "powershell" || name === "sh") {
      const cmd = typeof event.input?.command === "string" ? event.input.command : "";
      const DANGEROUS = [
        /settings-store\.json/i,
        /stop-process\b[^\n]*(docker|wsl|com\.docker)/i,
        /taskkill\b[^\n]*(docker|com\.docker|wsl|vmwp|vmmem)/i,
        /wsl\s+--shutdown/i,
        /wsl\s+--terminate\s+docker-desktop/i,
        /(docker\s+desktop\.exe|com\.docker\.backend)/i,
      ];
      if (DANGEROUS.some((re) => re.test(cmd))) {
        blocksThisTurn += 1;
        metric({ event: "host_life_block", tool: name });
        ctx.ui.notify("harness-guard: Docker/WSL engine-level operation blocked — human-only", "warn");
        return {
          block: true,
          reason:
            "[HOST-LIFE GUARD] Docker/WSL 引擎级操作只能由你在正常终端亲手执行（历史事故：2026-11-24 强杀 Docker 进程 + 改 settings-store.json 导致 WSL 崩溃、唯一出口 router 全线中断）。" +
            "如确需恢复操作（如 wsl --shutdown / 内存调整），请在正常终端自行运行并把输出贴回。",
        };
      }
    }
    if (name === "bash") {
      const cmd = typeof event.input?.command === "string" ? event.input.command : "";
      audit(`[bash] pid=${process.pid} cwd=${process.cwd()} cmd=${cmd.slice(0, 200)}`);
    }
    if (name === "bash" && isMutatingBash(event.input)) {
      mutatedThisTurn = true; // bash-side writes count too: the exit gate must not depend on the tool name
      return undefined;
    }
    // CLI-driven dispatches (python -m orchestrator..., pi subprocesses) leave no MCP tool call
    // for the hook to see; the command line is the signal then.
    const cmd = typeof event.input?.command === "string" ? event.input.command : "";
    if (name === "bash" && /(dispatch_subtask\(|run_plan\(|dispatch_tooled\(|orchestrator\.server)/.test(cmd)) {
      dispatchedThisTurn = true;
      metric({ event: "dispatch", tool: "bash-cli" });
    }
    if (name === "codemode") {
      // Issue #19: a codemode script calling tools.write is invisible to the write/edit branch below.
      const script = typeof event.input?.code === "string" ? event.input.code : "";
      const scan = scanCodemodeWrites(script);
      if (scan.calls === 0) return undefined;
      mutatedThisTurn = true;
      if (dispatchedThisTurn || overrideThisTurn || blocksThisTurn >= 1) return undefined;
      if (scan.literalLines > 40) {
        blocksThisTurn += 1;
        metric({ event: "direct_write", tool: "codemode", lines: scan.literalLines, blocked: true });
        ctx.ui.notify(`harness-guard: large codemode write (${scan.literalLines} lines) — plan/critic review first`, "warn");
        return { block: true, reason: writeRemediation("write inside codemode", scan.literalLines) };
      }
      if (scan.computed && !codemodeWarned) {
        // Partial coverage stated out loud beats silent coverage (#19).
        codemodeWarned = true;
        ctx.ui.notify("harness-guard: a codemode call writes with a computed payload; its size cannot be checked", "warn");
      }
      return undefined;
    }
    if (name !== "edit" && name !== "write") return undefined;

    mutatedThisTurn = true;

    if (dispatchedThisTurn || overrideThisTurn || blocksThisTurn >= 1) return undefined;

    // P1-2 fix: inspect actual edit/write size; small mechanical edits pass with zero friction!
    const lines = estimateChangedLines(name, event.input);
    const exceedsThreshold = (name === "edit" && lines > 15) || (name === "write" && lines > 40);
    if (!isLargeArchTurn && !exceedsThreshold) {
      metric({ event: "direct_write", tool: name, lines, blocked: false });
      return undefined;
    }

    blocksThisTurn += 1;
    metric({ event: "direct_write", tool: name, lines, blocked: true });
    ctx.ui.notify(`harness-guard: large ${name} (${lines} lines) — consider plan/critic review first`, "warn");
    return {
      block: true,
      reason: writeRemediation(name, lines),
    };
  });

  pi.on("tool_execution_end", async (event: any, ctx: any) => {
    const name = String(event.toolName || "");
    if (!/run_plan|dispatch_subagent|dispatch_tooled|codemode/.test(name)) return undefined;
    const parts = (event.result?.content || []) as any[];
    const text = parts.map((c) => (typeof c?.text === "string" ? c.text : "")).join(String.fromCharCode(10));
    finishAgent(ctx, `tool=${name}`, text);
    return undefined;
  });

  // Deterministic Exit Gate + State-Coupled Anti-Shirking Guard
  pi.on("agent_settled", async (_event: any, sctx: any) => {
    setVersionFooter(sctx);
    return undefined;
  });

  pi.on("agent_end", async (event: any, ctx: any) => {
    metric({
      event: "turn_end",
      mutated: mutatedThisTurn,
      dispatched: dispatchedThisTurn,
      override: overrideThisTurn,
    });

    const cwd = String(ctx?.cwd || process.cwd());

    // Review-contract self-loop (2026-11-22): judge EVERY substantial assistant
    // answer before the mutation early-return. The Python engine enforced this
    // in evaluate(), but production never called it — this TS gate early-returned
    // on non-mutated turns and never saw the text, so intercepts kept appearing
    // on all instances with no automatic redo. Bounce once, then halt.
    if (!bypassExitGateThisTurn) {
      try {
        const assistantText = extractLastAssistantText(event);
        if (assistantText.trim().length >= 40) {
          const jr = runReviewCheck(cwd, assistantText);
          if (jr && typeof jr.cap_note === "string" && jr.cap_note) {
            // Computed-cap correction: footer status only, never a transcript line
            // (2026-11-24): ctx.ui.notify rendered as a grey line the model then
            // echoed; the header is already normalized, so nothing needs announcing.
            // The gateway already normalized the header cap; nothing to announce. Kept as an audit
            // line only, because the terse footer item ("cap -> L4") read as noise (2026-11-24).
            audit(`[review-gate] cap normalized cwd=${cwd}`);
          }
          if (jr && Array.isArray(jr.violations) && jr.violations.length) {
            audit(`[review-gate] ${jr.violations.length} violation(s) cwd=${cwd}`);            if (reviewRetriesThisTurn >= 1) {
              const halt =
                "[HARNESS_REVIEW_GATE_RETRY] 重试后仍违规, 按 L2 上报人工复核, 不得再次自动打回。\n" +
                (jr.bounce_halt || "");
              ctx.ui.notify("harness-guard: review contract still violated — halting to user", "warn");
              if (typeof pi.sendUserMessage === "function") {
                pi.sendUserMessage(halt, { deliverAs: "followUp" });
              }
              return { continueWith: halt };
            }
            reviewRetriesThisTurn += 1;
            const bounce = jr.bounce_retry || "[HARNESS_REVIEW_GATE_RETRY] 请按契约重做本回合。";
            ctx.ui.notify(`harness-guard: review contract violation — bouncing (${jr.violations.length})`, "warn");
            if (typeof pi.sendUserMessage === "function") {
              pi.sendUserMessage(bounce, { deliverAs: "followUp" });
            }
            return { continueWith: bounce };
          }
          reviewRetriesThisTurn = 0;
        }
      } catch (e) {
        audit(`[review-gate] skipped: ${e}`);
      }
    }

    if (!mutatedThisTurn || bypassExitGateThisTurn) return undefined;

    // Controller-contract hardening: a task contract may declare that this task
    // must be decomposed and dispatched. Implementation turns without a dispatch
    // are bounced — 'the controller only accepts/analyzes/decomposes/dispatches'
    // is then enforced, not merely written in AGENTS.md.
    if (!dispatchedThisTurn && !overrideThisTurn) {
      try {
        const contractPath = join(cwd, ".pi", "task_contract.json");
        if (existsSync(contractPath)) {
          const contract = JSON.parse(readFileSync(contractPath, "utf-8"));
          if (contract.dispatch_required) {
            const bounce =
              `[CONTROLLER_CONTRACT_VIOLATION] .pi/task_contract.json declares dispatch_required=true ` +
              String.fromCharCode(10) +
              `but this turn edited files without dispatching any sub-agent. Decompose the work ` +
              `(plan_task / run_plan / dispatch_subagent), apply side effects via the sub-agent results, ` +
              `or set dispatch_required=false when you take implementation back on yourself (cite the L4 reason).`;
            ctx.ui.notify("harness-guard: dispatch_required contract violation — bouncing", "warn");
            audit(`[controller] dispatch_required violation cwd=${cwd}`);
            if (typeof pi.sendUserMessage === "function") {
              pi.sendUserMessage(bounce, { deliverAs: "followUp" });
            }
            return { continueWith: bounce };
          }
        }
      } catch {
        /* a broken contract file must not break the gate */
      }
    }
    const cfg = loadExitGateConfig(cwd);
    if (!cfg.enabled) return undefined;

    // Heavy-check cache (2026-11-24): `unit_tests` spawns the docker verify
    // container (15-40s) and ran after EVERY mutating turn, which froze the TUI
    // after each reply. The tree fingerprint (HEAD + porcelain status) identifies
    // the exact working state; if the same state was green minutes ago, reuse it.
    const cachePath = join(cwd, ".pi", "gate_cache.json");
    const treeFingerprint = (() => {
      try {
        const head = execSync("git rev-parse HEAD", { cwd, encoding: "utf-8", stdio: ["ignore", "pipe", "ignore"] }).trim();
        const st = execSync("git status --porcelain", { cwd, encoding: "utf-8", stdio: ["ignore", "pipe", "ignore"] });
        return createHash("sha1").update(head + "\n" + st).digest("hex").slice(0, 16);
      } catch { return ""; }
    })();
    let cached: { fingerprint?: string; ts?: number } = {};
    try { cached = JSON.parse(readFileSync(cachePath, "utf-8")); } catch { /* no cache */ }
    const cacheFresh = (nowMs: number) =>
      !!treeFingerprint && cached.fingerprint === treeFingerprint &&
      typeof cached.ts === "number" && (nowMs - cached.ts) < 30 * 60 * 1000;

    const failures: Array<{ name: string; tail: string }> = [];
    let reused = 0;
    for (const check of cfg.checks) {
      if (check.name === "unit_tests" && cacheFresh(Date.now())) {
        reused += 1;
        continue;
      }
      const res = runCheck(cwd, check, cfg.command_timeout_ms);
      if (!res.ok && check.required !== false) {
        failures.push({ name: check.name, tail: res.tail });
      }
    }
    const residue = scanResidueFiles(cwd, cfg.residue_globs);

    const policy = cfg.evidence_policy || "warn";
    const executedChecks = cfg.checks.length;
    const verdict =
      failures.length > 0 || residue.length > 0
        ? "red"
        : executedChecks === 0 ? "no_evidence" : "green";

    if (verdict === "green") {
      gateRetriesThisTurn = 0;
      lastErrorFingerprint = "";
      if (treeFingerprint) {
        try {
          mkdirSync(dirname(cachePath), { recursive: true });
          writeFileSync(cachePath, JSON.stringify({ fingerprint: treeFingerprint, ts: Date.now(), reused }), "utf-8");
        } catch { /* cache is an optimization, never a failure */ }
      }
      if (reused > 0) audit(`[exit-gate] reused cached unit_tests green (fingerprint ${treeFingerprint})`);
      appendLedger(cwd, { kind: "gate", verdict, fingerprint: "", checks: executedChecks, policy });
      return undefined;
    }

    // Issue #2: a green verdict must never come from "nothing was checked".
    if (verdict === "no_evidence") {
      appendLedger(cwd, { kind: "gate", verdict, fingerprint: "no_evidence", checks: 0, policy });
      const notice =
        "harness-guard: no checks configured (.pi/exit_gate.json missing or empty) — completion claims are unverified.";
      if (policy === "enforce" && typeof pi.sendUserMessage === "function") {
        const bounce =
          `[HARNESS_EXIT_GATE_RETRY] verdict=no_evidence. ${notice}` + String.fromCharCode(10) +
          "Add a check to .pi/exit_gate.json, or bind each quantified claim to an executed verification command, then re-verify.";
        ctx.ui.notify(notice, "warn");
        pi.sendUserMessage(bounce, { deliverAs: "followUp" });
        return { continueWith: bounce };
      }
      ctx.ui.notify(`${notice} (policy=${policy})`, "warn");
      return undefined;
    }

    const fingerprint = computeErrorFingerprint(failures, residue);
    const repeatedSameError = fingerprint === lastErrorFingerprint;
    lastErrorFingerprint = fingerprint;
    const priorRepeats = countLedgerRepeats(cwd, fingerprint);
    appendLedger(cwd, { kind: "gate", verdict, fingerprint, checks: executedChecks, policy,
      residue: residue.slice(0, 5), failures: failures.map((f) => f.name) });

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
    const escalationTag = repeatedSameError || priorRepeats >= 2
      ? "\n[ESCALATE_REASONING: high] Identical failure repeated; re-analyze root cause from first principles."
      : "";
    const ledgerTag = priorRepeats >= 2
      ? `\n[LOOP_LEDGER] This fingerprint already appeared ${priorRepeats} time(s) in earlier turns. Do not repeat the same fix: state a root-cause hypothesis, keep at most 2 candidate directions, then run one discriminating check or report the blocking unknown to the user.`
      : "";
    const shirkingWarning =
      shirkingHits.length > 0
        ? `\n[ANTI_SHIRKING_INTERCEPT] Detected buck-passing phrasing (${shirkingHits.join(", ")}) while verification is still red. Do NOT dismiss blocking failures as "pre-existing" or "unrelated"; fix them now.`
        : "";
    const failureBlock = failures.map((f) => `### Failed Check: ${f.name}\n\`\`\`\n${f.tail}\n\`\`\``).join("\n\n");
    const residueBlock = residue.length > 0 ? `\n### Leftover Residue Files (delete before finishing)\n- ${residue.join("\n- ")}` : "";

    const bouncePrompt =
      `[HARNESS_EXIT_GATE_RETRY] Attempt ${gateRetriesThisTurn}/${cfg.max_gate_retries} (fingerprint=${fingerprint}, verdict=${verdict}).\n` +
      `Your turn cannot finish because deterministic Exit Gate verification failed.${shirkingWarning}${escalationTag}${ledgerTag}\n\n` +
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
