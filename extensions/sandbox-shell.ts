/**
 * sandbox-shell — route pi shell work into the per-worktree Linux sandbox.
 *
 * Runtime topology:
 *   host plane   pi TUI + this extension (spawn orchestration only)
 *   exec plane   docker sandbox container (debian-slim, POSIX semantics)
 *   fallback     host Git Bash — declared and labeled [runner=...] in output
 *
 * WSL is deliberately NOT a rung: the worktree lives on the host filesystem
 * and containers are the primary POSIX runner.
 *
 * Lifecycle: session_start probes docker and brings the sandbox up for the
 * current worktree (compose project hbox-<hash(cwd)>, $SANDBOX_WORKTREE
 * bind-mounted at /workspace). The sh tool executes via docker compose exec;
 * without docker every result falls back to host Git Bash and says so.
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";

const HARNESS_HOME =
  process.env.HARNESS_HOME ??
  `${process.env.USERPROFILE ?? process.env.HOME ?? ""}/.pi/harness`;
const COMPOSE_FILE = `${HARNESS_HOME}/sandbox/compose.yaml`;
const IS_WIN = process.platform === "win32";
const HOST_BASH = IS_WIN ? "C:/Program Files/Git/bin/bash.exe" : "/bin/sh";

let runner: "docker" | "host" = "host";
let project = "";

interface RunResult {
  code: number;
  out: string;
}

function run(
  cmd: string,
  args: string[],
  opts: { cwd: string; timeoutMs?: number; signal?: AbortSignal; envExtra?: Record<string, string> },
): Promise<RunResult> {
  return new Promise((resolve) => {
    const child = spawn(cmd, args, {
      cwd: opts.cwd,
      env: { ...process.env, ...opts.envExtra },
      windowsHide: true,
    });
    let out = "";
    let settled = false;
    const finish = (code: number) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ code, out });
    };
    const timer = setTimeout(() => {
      child.kill();
      finish(124);
    }, opts.timeoutMs ?? 120000);
    opts.signal?.addEventListener("abort", () => {
      child.kill();
      finish(130);
    }, { once: true });
    const absorb = (d: Buffer) => {
      out += d.toString("utf8");
      if (out.length > 200000) out = out.slice(-200000);
    };
    child.stdout.on("data", absorb);
    child.stderr.on("data", absorb);
    child.on("close", (c) => finish(c ?? 1));
    child.on("error", (e) => {
      out += `\n[spawn error] ${e.message}`;
      finish(127);
    });
  });
}

const tail = (s: string, n = 300): string => (s.length > n ? s.slice(-n) : s);

export default function (pi: ExtensionAPI) {
  pi.on("session_start", async (_event, ctx) => {
    const cwd = process.cwd();
    project = `hbox-${createHash("md5").update(cwd).digest("hex").slice(0, 8)}`;
    const probe = await run("docker", ["compose", "version"], { cwd, timeoutMs: 15000 });
    if (probe.code !== 0) {
      runner = "host";
      ctx.ui.notify(
        "[sandbox-shell] docker not available — shell runs on host Git Bash. " +
          "Install Docker Desktop for the Linux sandbox.",
        "warning",
      );
      return;
    }
    const up = await run(
      "docker",
      ["compose", "-f", COMPOSE_FILE, "-p", project, "up", "-d"],
      { cwd, timeoutMs: 180000, envExtra: { SANDBOX_WORKTREE: cwd } },
    );
    if (up.code !== 0) {
      runner = "host";
      ctx.ui.notify(`[sandbox-shell] sandbox up failed (${tail(up.out)}) — host Git Bash fallback.`, "warning");
      return;
    }
    runner = "docker";
    ctx.ui.notify(`[sandbox-shell] runner=docker project=${project}`, "info");
  });

  pi.registerTool({
    name: "sh",
    label: "Sandbox Shell",
    description:
      "Execute a shell command in the Linux sandbox for this worktree " +
      "(declared fallback: host Git Bash). The worktree is mounted at " +
      "/workspace — use POSIX paths. Results are prefixed with [runner=...] " +
      "for evidence labeling.",
    parameters: Type.Object({
      command: Type.String({ description: "Command to execute" }),
      timeout: Type.Optional(Type.Number({ description: "Timeout seconds (default 120, max 600)" })),
    }),
    async execute(_id, params, signal) {
      const cwd = process.cwd();
      const timeoutMs = Math.min(Math.max(params.timeout ?? 120, 1), 600) * 1000;
      const dockerize = (cmd: string) => {
        const posix = cwd.replace(/\\/g, "/");
        return cmd.split(cwd).join("/workspace").split(posix).join("/workspace");
      };
      if (runner === "docker") {
        const execArgs = (c: string) => [
          "compose", "-f", COMPOSE_FILE, "-p", project,
          "exec", "-T", "sandbox", "sh", "-lc", `cd /workspace && ${c}`,
        ];
        let r = await run("docker", execArgs(dockerize(params.command)), { cwd, timeoutMs, signal });
        if (r.code !== 0 && /not running|No such container/i.test(r.out)) {
          await run("docker", ["compose", "-f", COMPOSE_FILE, "-p", project, "up", "-d"],
            { cwd, timeoutMs: 180000, envExtra: { SANDBOX_WORKTREE: cwd } });
          r = await run("docker", execArgs(dockerize(params.command)), { cwd, timeoutMs, signal });
        }
        return { content: [{ type: "text", text: `[runner=docker]\n${r.out}` }], details: {} };
      }
      const r = await run(HOST_BASH, ["-lc", params.command], { cwd, timeoutMs, signal });
      const label = IS_WIN ? "host-git-bash" : "host-sh";
      return { content: [{ type: "text", text: `[runner=${label}]\n${r.out}` }], details: {} };
    },
  });
}
