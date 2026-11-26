#!/usr/bin/env python3
"""In-place upgrade for existing installations (product path, v0.5.0).

Answers: "I installed v0.4.x — how do I get v0.5 without losing my .env,
knowledge store, exit-gate config and pending promotions?"

Design principles:
  * Idempotent — every migration records its id in .pi/upgrade_state.json and
    never re-runs; `python scripts/upgrade.py --check` previews the delta.
  * Non-destructive — .pi/, knowledge/, .env and promotions/ are copied to
    .upgrade-backup-<ts>/ BEFORE any mutation; rollback = restore the copy.
  * Honest verdict — the script exits non-zero unless compile + memory index +
    container rebuild + smoke test all pass (green state ownership).

Usage:
    python scripts/upgrade.py --check        # preview only
    python scripts/upgrade.py                # backup + migrate + rebuild + verify
    python scripts/upgrade.py --no-docker    # skip container rebuild (host-only)
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = REPO_ROOT / ".pi" / "upgrade_state.json"
INSTALLED_VERSION_PATH = REPO_ROOT / ".pi" / "installed_version"


def current_spec_version() -> str:
    spec = yaml.safe_load((REPO_ROOT / "harness.yaml").read_text(encoding="utf-8")) or {}
    return str(spec.get("version", "0.0.0"))


def installed_version() -> str | None:
    stamp = REPO_ROOT / ".pi" / "installed_version"
    if stamp.exists():
        return stamp.read_text(encoding="utf-8").strip() or None
    # v0.4.x predates the stamp: treat as 0.4.0 so all v0.5 migrations apply.
    return "0.4.0" if (REPO_ROOT / ".pi" / "exit_gate.json").exists() else None


def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"applied": []}
    return {"applied": []}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Migrations (idempotent, ordered). Each returns a human-readable change note.
# ---------------------------------------------------------------------------

def migrate_exit_gate_residue_globs(repo: Path) -> str:
    """v0.5 residue globs catch dotfile scratch; merge, never overwrite user config."""
    cfg_path = repo / ".pi" / "exit_gate.json"
    if not cfg_path.exists():
        return "no .pi/exit_gate.json — skipped"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    existing = list(cfg.get("residue_globs") or [])
    new_globs = [".*tmp*", ".*scratch*", ".*debug*", ".*.bak", ".*.orig"]
    added = [g for g in new_globs if g not in existing]
    if not added:
        return "residue globs already current"
    cfg["residue_globs"] = existing + added
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return f"residue globs += {added}"


def migrate_recompile_contract(repo: Path) -> str:
    """AGENTS.md / SKILL.md must match the new harness.yaml (check_docs enforces)."""
    out = subprocess.run(
        [sys.executable, str(repo / "scripts" / "compile_clients.py")],
        cwd=str(repo), capture_output=True, text=True, timeout=120,
    )
    if out.returncode != 0:
        raise RuntimeError(f"compile_clients failed: {out.stderr[-400:]}")
    return "AGENTS.md / SKILL.md recompiled"


def migrate_memory_index(repo: Path) -> str:
    """Rebuild FTS5 memory index (new L2 evidence, tokenizer unchanged)."""
    db = repo / "knowledge" / "memory_index.db"
    out = subprocess.run(
        [sys.executable, str(repo / "scripts" / "build_memory_index.py")],
        cwd=str(repo), capture_output=True, text=True, timeout=120,
    )
    if out.returncode != 0:
        raise RuntimeError(f"build_memory_index failed: {out.stderr[-400:]}")
    return f"memory index rebuilt ({db.name})"


def migrate_controller_metrics_ignore(repo: Path) -> str:
    """.gitignore additions for runtime metric files (v0.5)."""
    gi = repo / ".gitignore"
    lines = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    added = []
    for entry in (".pi/controller_metrics.jsonl", ".pi/hollow_audit.jsonl", ".pi/upgrade_state.json"):
        if entry not in lines:
            lines.append(entry)
            added.append(entry)
    if added:
        gi.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f".gitignore += {added}" if added else ".gitignore already current"


MIGRATIONS: list[tuple[str, str, object]] = [
    ("v0.5-exit-gate-residue-globs", "merge dotfile residue globs into .pi/exit_gate.json", migrate_exit_gate_residue_globs),
    ("v0.5-gitignore-runtime", "ignore runtime metric/upgrade state files", migrate_controller_metrics_ignore),
    ("v0.5-recompile-contract", "recompile AGENTS.md / SKILL.md from harness.yaml", migrate_recompile_contract),
    ("v0.5-memory-index", "rebuild FTS5 memory index", migrate_memory_index),
]


def backup(repo: Path, sink: Path) -> list[str]:
    """Copy mutable state before migrating. Returns list of backed-up paths.

    sink may already exist when it is created by tempfile.mkdtemp (outside-repo
    backups), so this tolerates an existing directory.
    """
    backed: list[str] = []
    sink.mkdir(parents=True, exist_ok=True)
    for rel in (".pi", "knowledge", ".env", "promotions"):
        src = repo / rel
        if src.is_dir():
            shutil.copytree(src, sink / rel, dirs_exist_ok=True)
            backed.append(rel)
        elif src.is_file():
            sink.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, sink / rel)
            backed.append(rel)
    return backed



HA_OVERLAY = "docker-compose.ha.yml"
GATE_URL = "http://127.0.0.1:8787/__gate/status"


def gate_status(timeout: float = 3.0) -> dict | None:
    """The gate's view of the world, or None when the gate is not serving 8787."""
    try:
        with urllib.request.urlopen(GATE_URL, timeout=timeout) as resp:
            return json.loads(resp.read() or b"{}")
    except (OSError, ValueError):
        return None


def wait_until_healthy(name: str, timeout: float = 120.0, interval: float = 2.0) -> bool:
    """Switching before the new backend answers sends the first request into a dead socket.

    Observed 2026-11-26: the upgrade switched to a just-recreated green before it listened, the gate
    failed the request over to blue and auto-flipped back - no user-visible error, but the new image
    never took traffic.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = gate_status()
        if status and (status.get("healthy") or {}).get(name):
            return True
        time.sleep(interval)
    return False


def upgrade_plan(status: dict | None) -> list[list[str]]:
    """Solo mode recreates the single service; HA mode recreates the IDLE side, then switches."""
    if not status:
        return [["docker", "compose", "--profile", "solo", "up", "-d", "harness-backend"]]
    active = str(status.get("active") or "blue")
    idle = "green" if active == "blue" else "blue"
    return [
        ["docker", "compose", "-f", "docker-compose.yml", "-f", HA_OVERLAY,
         "up", "-d", "--no-deps", "--force-recreate", f"backend-{idle}"],
        [sys.executable, str(REPO_ROOT / "scripts" / "router_switch.py"), "switch", idle],
    ]

def docker_rebuild() -> str:
    # docker-compose.yml declares env_file: .env; compose fails hard when it
    # is missing (live WSL upgrade incident 2026-11-22). A keyless install is
    # valid — seed from the example rather than failing the whole upgrade.
    env_path = REPO_ROOT / ".env"
    example = REPO_ROOT / ".env.example"
    seeded = False
    if not env_path.exists() and example.exists():
        shutil.copy2(example, env_path)
        seeded = True
    # 2026-11-25: a raw `up -d --build` baked a tree with a SyntaxError and the only router went into
    # a Restarting loop. The build now passes an in-image import gate first, and an HA deployment
    # upgrades the IDLE backend and switches, so the serving side is never recreated underneath the
    # client.
    build = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "router_build.py")],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=1800,
    )
    if build.returncode != 0:
        raise RuntimeError(f"image refused: {build.stderr[-400:]}")
    for step in upgrade_plan(gate_status()):
        out = subprocess.run(step, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=900)
        if out.returncode != 0:
            raise RuntimeError(f"upgrade step failed ({' '.join(step)}): {out.stderr[-300:]}")
        if "switch" not in step:
            target = step[-1].split("backend-")[-1]
            if target in ("blue", "green") and not wait_until_healthy(target):
                raise RuntimeError(
                    f"backend-{target} did not become healthy within the window; the switch was not "
                    f"made, so the serving side is untouched")
    # smoke test with startup grace: compose up returns before uvicorn is
    # listening (live race 2026-11-24); --noproxy guards host proxy envs.
    health = None
    for _attempt in range(6):
        time.sleep(5)
        health = subprocess.run(
            ["curl", "-s", "--noproxy", "*", "-m", "5", "http://127.0.0.1:8787/health"],
            capture_output=True, text=True, timeout=20,
        )
        if health.returncode == 0 and '"status"' in health.stdout:
            break
    if health is None or health.returncode != 0 or '"status"' not in health.stdout:
        raise RuntimeError(
            f"backend smoke test failed after retries: {(health.stdout if health else '')[-200:]}")
    note = "containers rebuilt, /health ok"
    if seeded:
        note += " (.env seeded from .env.example — no keys, set them in .env)"
    return note


def verify() -> str:
    out = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=900,
    )
    if out.returncode != 0:
        raise RuntimeError(f"unit tests red after upgrade: {out.stderr[-500:]}")
    tail = [l for l in out.stderr.splitlines() if l.strip()][-1]
    return f"unit tests green ({tail})"


def step_install_global() -> str:
    """Refresh the global install: extensions, sandbox def, session contract, pi settings."""
    out = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "install_global.py")],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120,
    )
    if out.returncode != 0:
        raise RuntimeError(f"install_global failed: {out.stderr[-400:]}")
    return "global install synced (extension + sandbox + session contract + pi settings)"


def sandbox_build() -> str:
    """Build the global sandbox image so first use needs no build."""
    compose = Path.home() / ".pi" / "harness" / "sandbox" / "compose.yaml"
    if not compose.exists():
        raise RuntimeError("sandbox compose missing — install_global did not sync it")
    out = subprocess.run(
        ["docker", "compose", "-f", str(compose), "build"],
        cwd=str(compose.parent), capture_output=True, text=True, timeout=900,
        # compose interpolates volumes even for `build`; the extension-owned
        # $SANDBOX_WORKTREE guard would abort — feed a build-only placeholder
        env={**os.environ, "SANDBOX_WORKTREE": str(compose.parent)},
    )
    if out.returncode != 0:
        raise RuntimeError(f"sandbox build failed: {out.stderr[-400:]}")
    return "harness-sandbox:local built"


def plane_report(skip_docker: bool) -> str:
    """Every plane checked by scripts/check_env.py (--skip-stamp: stamped below)."""
    cmd = [sys.executable, str(REPO_ROOT / "scripts" / "check_env.py"), "--skip-stamp"]
    if skip_docker:
        cmd.append("--no-docker")
    out = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120)
    lines = [l for l in out.stdout.splitlines() if l.strip()]
    if out.returncode != 0:
        raise RuntimeError("plane alignment failed:\n" + "\n".join(lines[-12:]))
    return f"all planes aligned ({len(lines)} rows)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="preview pending migrations, change nothing")
    ap.add_argument("--no-docker", action="store_true", help="skip container rebuild")
    ap.add_argument("--keep-backup", action="store_true", help="keep backup dir (default: delete on success)")
    args = ap.parse_args()

    cur = installed_version()
    new = current_spec_version()
    state = _load_state()
    pending = [m for m in MIGRATIONS if m[0] not in state["applied"]]
    print(f"installed: {cur or '(none — fresh install, use scripts/install.py)'}")
    print(f"repo spec : v{new}")
    if not pending:
        print("no pending migrations")
        if args.check:
            return 0
    else:
        print(f"pending migrations: {len(pending)}")
        for mid, desc, _ in pending:
            print(f"  - {mid}: {desc}")
    if args.check:
        return 0

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # Backups live OUTSIDE the source tree (issue: dev/runtime separation). Staging
    # runtime artifacts inside the repo dirtied git status on failure paths.
    backup_dir = Path(tempfile.mkdtemp(prefix=f"harness-upgrade-backup-{ts}-"))
    print(f"\nbackup -> {backup_dir}")
    try:
        backed = backup(REPO_ROOT, backup_dir)
        print(f"  backed up: {', '.join(backed)}")

        for mid, desc, fn in pending:
            print(f"migrate {mid} ...")
            note = fn(REPO_ROOT)  # type: ignore[operator]
            state["applied"].append(mid)
            print(f"  {note}")
        _save_state(state)

        print("sync global install ...")
        print(f"  {step_install_global()}")
        if not args.no_docker:
            print("rebuild containers ...")
            print(f"  {docker_rebuild()}")
            print("build sandbox image ...")
            print(f"  {sandbox_build()}")
        print("sync user-level skills ...")
        out = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "install_user_skills.py")],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
        )
        print(f"  {out.stdout.strip() or out.stderr.strip()}")
        print("verify ...")
        print(f"  {verify()}")
        print("plane alignment ...")
        print(f"  {plane_report(args.no_docker)}")

        INSTALLED_VERSION_PATH.write_text(f"v{new}\n", encoding="utf-8")
        if not args.keep_backup:
            shutil.rmtree(backup_dir, ignore_errors=True)
            print(f"\nupgrade complete: {cur} -> v{new} (backup removed; --keep-backup to retain)")
        else:
            print(f"\nupgrade complete: {cur} -> v{new} (backup kept at {backup_dir})")
        return 0
    except Exception as exc:  # noqa: BLE001 - report with rollback pointer
        print(f"\nUPGRADE FAILED: {exc}", file=sys.stderr)
        print(f"rollback: restore {backup_dir}/ over the repo, then re-run.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
