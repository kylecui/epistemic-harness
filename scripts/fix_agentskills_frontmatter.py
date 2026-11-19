#!/usr/bin/env python3
"""Repair YAML frontmatter in ~/.agents/skills/*/SKILL.md (cross-CLI shared skills).

Symptom: Pi warns "Nested mappings are not allowed in compact mappings" because
unquoted scalar values contain ': ' (colon + space), e.g.
    description: Foo bar: baz        # invalid YAML
Fix: wrap such values in double quotes (escaping as needed). Zero semantic change;
body of SKILL.md is never touched. Originals are kept as SKILL.md.bak.

Usage: python scripts/fix_agentskills_frontmatter.py [--root PATH] [--apply]
       default root: ~/.agents/skills ; default mode: dry-run
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

import yaml

KEY_LINE = re.compile(r"^([A-Za-z][\w-]*):(?! )(.*)$|^([A-Za-z][\w-]*): (.+)$")


def needs_quoting(value: str) -> bool:
    v = value.strip()
    if not v:
        return False
    if (v[0] == v[-1] == '"') or (v[0] == v[-1] == "'"):
        return False  # already quoted
    if ": " in v or v.endswith(":"):
        return True
    if v[0] in "{}[]#&*!|>%@`" or v.startswith("- "):
        return True
    return False


def fix_frontmatter(text: str) -> tuple[str, int]:
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return text, 0
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return text, 0
    fixed = 0
    for i in range(1, end):
        m = re.match(r"^([A-Za-z][\w-]*):(?://| )(.*)$", lines[i])
        if not m or not m.group(2).strip():
            continue
        key, value = m.group(1), m.group(2)
        if needs_quoting(value.strip()):
            escaped = value.strip().replace("\\", "\\\\").replace('"', '\\"')
            lines[i] = f'{key}: "{escaped}"'
            fixed += 1
    return "\n".join(lines), fixed


def validate_frontmatter(text: str) -> str | None:
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            block = "\n".join(lines[1:i])
            try:
                yaml.safe_load(block)
            except yaml.YAMLError as exc:
                return str(exc).split("\n")[0]
            return None
    return "frontmatter not terminated"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path.home() / ".agents" / "skills"))
    ap.add_argument("--apply", action="store_true", help="write fixes (default: dry-run)")
    args = ap.parse_args()

    root = Path(args.root)
    total = fixed_total = invalid_after = 0
    for skill_md in sorted(root.glob("*/SKILL.md")):
        total += 1
        original = skill_md.read_text(encoding="utf-8")
        err_before = validate_frontmatter(original)
        if err_before is None:
            continue
        fixed_text, n = fix_frontmatter(original)
        err_after = validate_frontmatter(fixed_text)
        status = "FIXED" if err_after is None else f"STILL INVALID ({err_after})"
        print(f"{skill_md.parent.name:32s} {status}  (+{n} quoted)")
        if err_after is None:
            fixed_total += 1
            if args.apply:
                shutil.copy2(skill_md, skill_md.with_suffix(".md.bak"))
                skill_md.write_text(fixed_text, encoding="utf-8")
        else:
            invalid_after += 1
    mode = "APPLIED" if args.apply else "DRY-RUN (use --apply to write)"
    print(f"\n{mode}: scanned {total}, repairable {fixed_total}, unrepairable {invalid_after}")


if __name__ == "__main__":
    main()
