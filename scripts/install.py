#!/usr/bin/env python3
"""Cross-platform installer / readiness checker for the Epistemic Harness.

Design (install is part of the release, not an afterthought):

  1. Detect the platform (OS, shell family, container runtime).
  2. Check prerequisites and report a capability matrix.
  3. Full path  : Docker + git + Python 3.10+  -> container-first verification,
                  backend via docker compose, every feature available.
  4. Fallback   : no Docker                 -> host-runner mode with an explicit
                  LIMITED-SUPPORT list + warning. Nothing silently degrades.
  5. Finish     : venv, requirements, git hooks, client compilation, smoke test.

Usage:
    python scripts/install.py            # full setup (idempotent)
    python scripts/install.py --check    # report only, change nothing
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
PY_MINOR_MIN = 10

LIMITED_SUPPORT_NO_DOCKER = [
    "verification runs on the HOST shell (cmd.exe/PowerShell vs POSIX sh): shell-dependent checks may behave differently",
    "no container isolation: checks share the host filesystem and process space",
    "batch-docker execution disabled (one process per check instead of one container per batch)",
    "image-pinned determinism unavailable: verdicts record runner=host only",
    "CRLF risk is higher: the eol pre-commit hook still applies, but .gitattributes is your only git-side guard",
]
LIMITED_SUPPORT_NO_GIT = [
    "no version-control integration: residue scan and pre-commit eol hook disabled",
]


def _sh(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=timeout)


def detect() -> dict:
    system = platform.system().lower()
    shell_family = "posix" if system in ("linux", "darwin") else (
        "posix-via-git-bash" if shutil.which("sh") else "windows-native")
    docker = False
    if shutil.which("docker"):
        try:
            docker = _sh(["docker", "info"], timeout=15).returncode == 0
        except (OSError, subprocess.SubprocessError):
            docker = False
    git = bool(shutil.which("git"))
    python_ok = sys.version_info >= (3, PY_MINOR_MIN)
    venv = (REPO_ROOT / ".venv").exists()
    return {
        "os": platform.system(), "platform": platform.platform(),
        "shell_family": shell_family,
        "python": platform.python_version(), "python_ok": python_ok,
        "git": git, "docker": docker, "venv_present": venv,
        "support_tier": "full" if (docker and git and python_ok) else "limited",
    }


def report(info: dict) -> str:
    lines = [
        f"platform   : {info['platform']}",
        f"shell      : {info['shell_family']}",
        f"python     : {info['python']} (>=3.{PY_MINOR_MIN}: {info['python_ok']})",
        f"git        : {info['git']}",
        f"docker     : {info['docker']}",
        f"venv       : {info['venv_present']}",
        f"support    : {info['support_tier'].upper()}",
    ]
    if info["support_tier"] == "limited":
        lines.append("WARNING: limited-support mode. The following limitations apply:")
        if not info["docker"]:
            for item in LIMITED_SUPPORT_NO_DOCKER:
                lines.append(f"  - {item}")
        if not info["git"]:
            for item in LIMITED_SUPPORT_NO_GIT:
                lines.append(f"  - {item}")
    return "\n".join(lines)


def setup(info: dict) -> list[str]:
    steps: list[str] = []
    if not info["python_ok"]:
        print(f"FATAL: Python 3.{PY_MINOR_MIN}+ required, found {info['python']}", file=sys.stderr)
        sys.exit(2)

    venv_dir = REPO_ROOT / ".venv"
    venv_py = venv_dir / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
    if not venv_py.exists():
        subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)])
        steps.append("venv created")
    subprocess.check_call([str(venv_py), "-m", "pip", "install", "-q", "-r", "requirements.txt"], cwd=str(REPO_ROOT))
    steps.append("requirements installed")

    if info["git"]:
        subprocess.check_call([str(venv_py), "scripts/install_git_hooks.py"], cwd=str(REPO_ROOT))
        steps.append("git hooks installed (core.hooksPath=scripts/git-hooks)")

    subprocess.check_call([str(venv_py), "scripts/compile_clients.py"], cwd=str(REPO_ROOT))
    steps.append("clients compiled (AGENTS.md / gemini / SKILL)")

    if info["docker"]:
        proc = _sh(["docker", "image", "inspect", "epistemic-verify:local"], timeout=20)
        if proc.returncode != 0:
            subprocess.check_call(["docker", "build", "-q", "-f", "Dockerfile.verify",
                                   "-t", "epistemic-verify:local", "."], cwd=str(REPO_ROOT))
        steps.append("verify image ready (epistemic-verify:local)")
    else:
        steps.append("verify image SKIPPED (no docker) — host fallback active, see LIMITED SUPPORT list")

    subprocess.check_call([str(venv_py), "scripts/build_memory_index.py", "--db"], cwd=str(REPO_ROOT))
    steps.append("memory index built")
    return steps


SHELL_MARKER_BEGIN = "# >>> harness shell >>>"
SHELL_MARKER_END = "# <<< harness shell <<<"


def _shell_snippet(ps1: bool) -> str:
    """Idempotent shell block: `harness` launcher + `hvx` alias."""
    if ps1:
        body = (
            f'function harness {{ & "{REPO_ROOT}\\start_harness.ps1" -Global @args }}\n'
            f'function hvx {{ & "{REPO_ROOT}\\scripts\\hvx.ps1" @args }}'
        )
    else:
        body = (
            f'harness() {{ "{REPO_ROOT}/start_harness.sh" --global "$@"; }}\n'
            f'alias hvx="{REPO_ROOT}/scripts/hvx"'
        )
    return f"{SHELL_MARKER_BEGIN}\n{body}\n{SHELL_MARKER_END}\n"


def _append_idempotent(target: Path, block: str) -> str:
    """Append the block if the marker is absent. Returns what happened."""
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    if SHELL_MARKER_BEGIN in existing:
        return f"already present in {target}"
    with target.open("a", encoding="utf-8", newline="\n") as fh:
        if existing and not existing.endswith("\n"):
            fh.write("\n")
        fh.write("\n" + block)
    return f"appended to {target}"


def shell_targets() -> list[tuple[str, Path, bool]]:
    home = Path.home()
    targets: list[tuple[str, Path, bool]] = []
    profile = os.environ.get("PROFILE")
    ps_profile = Path(profile) if profile else home / "Documents" / "WindowsPowerShell" / "Microsoft.PowerShell_profile.ps1"
    targets.append(("powershell", ps_profile, True))
    for rc in (".bashrc", ".zshrc"):
        targets.append((rc[1:], home / rc, False))
    return targets


def shell_report(apply: bool) -> str:
    lines: list[str] = []
    for name, path, ps1 in shell_targets():
        if apply:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                lines.append(f"  [{name}] {_append_idempotent(path, _shell_snippet(ps1))} — restart your shell")
            except OSError as exc:
                lines.append(f"  [{name}] FAILED: {exc}")
        else:
            verb = "would be added to" if not (path.exists() and SHELL_MARKER_BEGIN in path.read_text(encoding="utf-8", errors="replace")) else "already present in"
            lines.append(f"  [{name}] {verb} {path}  (run with --with-shell to apply)")
    lines.append("  [cmd.exe] no automatic integration: run start_harness.ps1 from PowerShell,")
    lines.append("            or add the repo to PATH and use scripts\\hvx.ps1 directly.")
    return "\n".join(lines)


def main() -> int:
    check_only = "--check" in sys.argv
    apply_shell = "--with-shell" in sys.argv
    info = detect()
    print(report(info))
    if check_only:
        return 0 if info["python_ok"] else 2
    print("\nsetup:")
    for step in setup(info):
        print(f"  - {step}")
    print("\nshell integration:")
    print(shell_report(apply_shell))
    print("\nsmoke test:")
    venv_py = REPO_ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
    rc = subprocess.call([str(venv_py), "scripts/verify.py"], cwd=str(REPO_ROOT))
    if rc != 0:
        print(f"smoke test FAILED (exit {rc})", file=sys.stderr)
        return rc
    print("smoke test ok — harness ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
