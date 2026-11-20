"""Tooled sub-agents: isolated `pi` processes that can actually read/write/run.

Rationale (review P1-2): the HTTP sub-agents have no tools, so they can only return text
and the controller ends up writing code by hand. For implementation work we instead spawn
a real Pi process in the target workspace:

    pi -p "<task>" --provider harness-router --model <m> --no-session --no-mcp --no-skills

Properties:
  - Process isolation: separate context, separate session, hard timeout + kill.
  - Workspace-scoped: `workdir` must be inside an allowed root (repo root or cwd) by default.
  - Host-only by design: it needs the user's real filesystem and Pi credentials. In the
    container there is no `pi` binary, so the MCP tool returns an instructive error there.

Pure-Python, no shell interpolation: argv is passed as a list.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent

MODEL_BY_PROFILE: dict[str, str] = {
    "explorer": "opencode-deepseek-v4.1-flash",
    "coder": "opencode-deepseek-v4.1-flash",
    "deep": "opencode-deepseek-v4.1-flash",
    "critic": "opencode-deepseek-v4.1-flash",
}

DEFAULT_TIMEOUT = 600.0


def _allowed_roots() -> list[Path]:
    roots = [REPO_ROOT, Path.cwd().resolve()]
    extra = os.getenv("HARNESS_TOOLED_ROOTS", "").strip()
    if extra:
        for part in extra.split(os.pathsep):
            if part.strip():
                roots.append(Path(part).expanduser().resolve())
    return roots


def _validate_workdir(workdir: str | None) -> Path:
    if not workdir:
        return REPO_ROOT
    target = Path(workdir).expanduser().resolve()
    if not target.exists() or not target.is_dir():
        raise ValueError(f"workdir does not exist: {target}")
    allowed = _allowed_roots()
    if not any(target == root or root in target.parents for root in allowed):
        raise PermissionError(
            f"workdir {target} is outside allowed roots {[str(r) for r in allowed]}; "
            "set HARNESS_TOOLED_ROOTS to extend."
        )
    return target


def dispatch_tooled(
    task_text: str,
    workdir: str | None = None,
    profile: str = "coder",
    model: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    pi_bin: str | None = None,
    extra_args: list[str] | None = None,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> dict[str, Any]:
    """Run one tooled sub-agent. Returns a structured result (never raises on task failure)."""
    binary = pi_bin or os.getenv("HARNESS_PI_BIN") or shutil.which("pi")
    if not binary:
        return {
            "profile": profile,
            "status": "unavailable",
            "error": "pi binary not found (tooled sub-agents run host-side only)",
        }
    try:
        cwd = _validate_workdir(workdir)
    except (ValueError, PermissionError) as exc:
        return {"profile": profile, "status": "rejected", "error": str(exc)}

    argv = [
        binary, "-p", task_text,
        "--provider", "harness-router",
        "--model", model or MODEL_BY_PROFILE.get(profile, MODEL_BY_PROFILE["coder"]),
        "--no-session",
        "--no-mcp",
        "--no-skills",
    ] + (extra_args or [])

    run = runner or subprocess.run
    started = time.time()
    try:
        proc = run(
            argv, cwd=str(cwd), capture_output=True, text=True,
            timeout=timeout, env={**os.environ, "HARNESS_SUBAGENT": profile},
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "profile": profile, "status": "timeout", "workdir": str(cwd),
            "duration_sec": round(time.time() - started, 1),
            "stdout": (exc.stdout or ""), "stderr": (exc.stderr or ""),
            "error": f"exceeded {timeout}s",
        }
    except OSError as exc:
        return {"profile": profile, "status": "error", "workdir": str(cwd), "error": str(exc)}

    return {
        "profile": profile,
        "status": "ok" if proc.returncode == 0 else "error",
        "workdir": str(cwd),
        "exit_code": proc.returncode,
        "duration_sec": round(time.time() - started, 1),
        "stdout": proc.stdout or "",
        "stderr": proc.stderr or "",
    }


def main() -> None:  # pragma: no cover - thin CLI
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Run a tooled sub-agent in an isolated pi process")
    ap.add_argument("task")
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--profile", default="coder")
    ap.add_argument("--model", default=None)
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    args = ap.parse_args()
    print(json.dumps(dispatch_tooled(args.task, args.workdir, args.profile, args.model, args.timeout),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()
