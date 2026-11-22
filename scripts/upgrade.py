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
    """Copy mutable state before migrating. Returns list of backed-up paths."""
    backed: list[str] = []
    sink.mkdir(parents=True, exist_ok=False)
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


def docker_rebuild() -> str:
    out = subprocess.run(
        ["docker", "compose", "up", "-d", "--build"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=900,
    )
    if out.returncode != 0:
        raise RuntimeError(f"docker compose rebuild failed: {out.stderr[-400:]}")
    health = subprocess.run(
        ["curl", "-s", "-m", "10", "http://127.0.0.1:8787/health"],
        capture_output=True, text=True, timeout=20,
    )
    if health.returncode != 0 or '"status"' not in health.stdout:
        raise RuntimeError(f"backend smoke test failed: {health.stdout[-200:]}")
    return "containers rebuilt, /health ok"


def verify() -> str:
    out = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=900,
    )
    if out.returncode != 0:
        raise RuntimeError(f"unit tests red after upgrade: {out.stderr[-500:]}")
    tail = [l for l in out.stderr.splitlines() if l.strip()][-1]
    return f"unit tests green ({tail})"


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
    backup_dir = REPO_ROOT / f".upgrade-backup-{ts}"
    print(f"\nbackup -> {backup_dir.name}")
    try:
        backed = backup(REPO_ROOT, backup_dir)
        print(f"  backed up: {', '.join(backed)}")

        for mid, desc, fn in pending:
            print(f"migrate {mid} ...")
            note = fn(REPO_ROOT)  # type: ignore[operator]
            state["applied"].append(mid)
            print(f"  {note}")
        _save_state(state)

        if not args.no_docker:
            print("rebuild containers ...")
            print(f"  {docker_rebuild()}")
        print("verify ...")
        print(f"  {verify()}")

        INSTALLED_VERSION_PATH.write_text(f"v{new}\n", encoding="utf-8")
        if not args.keep_backup:
            shutil.rmtree(backup_dir, ignore_errors=True)
            print(f"\nupgrade complete: v{cur} -> v{new} (backup removed; --keep-backup to retain)")
        else:
            print(f"\nupgrade complete: v{cur} -> v{new} (backup kept at {backup_dir.name})")
        return 0
    except Exception as exc:  # noqa: BLE001 - report with rollback pointer
        print(f"\nUPGRADE FAILED: {exc}", file=sys.stderr)
        print(f"rollback: restore {backup_dir.name}/ over the repo, then re-run.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
