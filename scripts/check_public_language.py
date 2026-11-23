#!/usr/bin/env python3
"""Public-language gate (README convention, 2026-11-24).

Public content defaults to English unless explicitly declared otherwise.
This gate polices the one public surface that is deterministically checkable
at exit-gate time: unpushed commit messages. A message containing CJK is
allowed only when it carries the explicit exception marker `[zh]` or
`Lang: zh`.

Out of scope by design: chat replies (private, follow the user's language),
README_ZH.md and marked private notes (supplementary by convention),
issue/PR bodies (enforced by authoring convention, not gate-scanable here).

Runner note: if git is unavailable in the gate runner, the check reports
`SKIP` and exits 0 — it binds on runners that have git (host/WSL).

Exit 0 = clean (or skipped); 1 = violating commit found.
"""

from __future__ import annotations

import re
import subprocess
import sys

CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")
MARKERS = ("[zh]", "lang:zh", "lang: zh")


def has_cjk(text: str) -> bool:
    return bool(CJK.search(text))


def message_declared_zh(message: str) -> bool:
    low = message.lower()
    return any(m in low for m in MARKERS)


def unpushed_messages() -> list[tuple[str, str]] | None:
    """(sha, message) for commits ahead of upstream; None if not checkable."""
    try:
        base = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            capture_output=True,
        )
        if base.returncode != 0:
            return []  # no upstream yet: nothing published to police
        rng = base.stdout.decode("utf-8", "replace").strip()
        out = subprocess.run(
            ["git", "log", f"{rng}..HEAD", "--format=%H%x1f%B%x1e"],
            capture_output=True,
        )
    except FileNotFoundError:
        return None  # git unavailable in this runner
    text = out.stdout.decode("utf-8", "replace")
    entries: list[tuple[str, str]] = []
    for chunk in text.split("\x1e"):
        chunk = chunk.strip("\n")
        if not chunk.strip():
            continue
        sha, _, body = chunk.partition("\x1f")
        entries.append((sha.strip(), body.strip()))
    return entries


def main() -> int:
    messages = unpushed_messages()
    if messages is None:
        print("public-language gate: SKIP (git unavailable in this runner)")
        return 0
    bad = [
        (sha, msg)
        for sha, msg in messages
        if has_cjk(msg) and not message_declared_zh(msg)
    ]
    if bad:
        print("public-language gate: non-English commit message(s) without an explicit [zh] marker:")
        for sha, msg in bad:
            print(f"  {sha[:10]}  {' '.join(msg.split())[:120]}")
        print("Fix: rewrite the message in English, or add an explicit [zh] / 'Lang: zh' marker.")
        return 1
    print(f"public-language gate: OK ({len(messages)} unpushed commit(s) checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
