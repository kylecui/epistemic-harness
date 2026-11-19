#!/usr/bin/env python3
"""Apply skills-inventory.md verdicts: mark every 手动 skill with disable-model-invocation: true.

Manual skills stay invocable via /skill:name but disappear from the system-prompt
advertisement (model can no longer auto-select them). 自动 skills are left untouched.
Backups: SKILL.md.bak next to each modified file. Idempotent; validate YAML after edit.

Usage: python scripts/apply_inventory_verdicts.py [--dry-run]
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

import yaml

INVENTORY = Path(__file__).resolve().parent.parent / "docs" / "skills-inventory.md"
ROW = re.compile(r"^\| `([a-z0-9-]+)` \| (共享|Pi用户级) \|.*\| \*\*(自动|手动)\*\* \|", re.M)
ROOTS = [Path.home() / ".agents" / "skills", Path.home() / ".pi" / "agent" / "skills"]


def locate(skill: str) -> Path | None:
    for root in ROOTS:
        md = root / skill / "SKILL.md"
        if md.is_file():
            return md
    return None


def set_manual_flag(md: Path, apply: bool) -> str:
    text = md.read_text(encoding="utf-8")
    m = re.match(r"^(---\n)(.*?)(\n---\n)", text, re.S)
    if not m:
        return "no-frontmatter"
    head, fm, tail = m.group(1), m.group(2), m.group(3)
    if re.search(r"^disable-model-invocation:\s*true\s*$", fm, re.M):
        return "already"
    if re.search(r"^disable-model-invocation:", fm, re.M):
        fm = re.sub(r"^disable-model-invocation:.*$", "disable-model-invocation: true", fm, flags=re.M)
        action = "updated"
    else:
        fm += "\ndisable-model-invocation: true"
        action = "added"
    new_text = head + fm + tail + text[m.end():]
    try:
        yaml.safe_load(fm)
    except yaml.YAMLError:
        return "yaml-error(kept)"
    if apply:
        shutil.copy2(md, md.with_suffix(".md.bak"))
        md.write_text(new_text, encoding="utf-8")
    return action


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    verdicts = {name: v for name, _src, v in ROW.findall(INVENTORY.read_text(encoding="utf-8"))}
    manual = sorted(n for n, v in verdicts.items() if v == "手动")
    auto = sorted(n for n, v in verdicts.items() if v == "自动")
    counts: dict[str, int] = {}
    missing: list[str] = []
    for name in manual:
        md = locate(name)
        if md is None:
            missing.append(name)
            continue
        action = set_manual_flag(md, apply=not args.dry_run)
        counts[action] = counts.get(action, 0) + 1
        if action in ("added", "updated"):
            print(f"  {name:36s} {action}")
    mode = "DRY-RUN" if args.dry_run else "APPLIED"
    print(f"\n{mode}: manual={len(manual)} -> {counts} | auto(untouched)={len(auto)} | missing={missing or 'none'}")


if __name__ == "__main__":
    main()
