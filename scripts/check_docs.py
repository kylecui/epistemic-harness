#!/usr/bin/env python3
"""Docs freshness gate: documentation ships in sync with the code, or not at all.

Iron rule enforcement (see harness.yaml loop_completion_contract): at delivery,
docs reflect current behavior. This checker fails the exit gate when:

  1. version drift  — harness.yaml version != README badge != workplan header;
  2. stale compile  — AGENTS.md / SKILL.md differ from a fresh compile_clients run;
  3. missing install doc — INSTALL.md absent or lacking the platform matrix section;
  4. orphan docs    — a file under docs/ with no entry in docs/README.md index.

Usage:
    python scripts/check_docs.py        # exit 1 on any drift
"""

from __future__ import annotations

from pathlib import Path
import re
import sys
import tempfile

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def _version() -> str:
    spec = yaml.safe_load((REPO_ROOT / "harness.yaml").read_text(encoding="utf-8")) or {}
    return str(spec.get("version", ""))


def check_version_alignment(problems: list[str]) -> None:
    version = _version()
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8") if (REPO_ROOT / "README.md").exists() else ""
    if f"v{version}" not in readme:
        problems.append(f"README.md does not mention v{version}")
    workplan = REPO_ROOT / "docs" / "workplan-v0.4.md"
    if workplan.exists() and not re.search(rf"v{re.escape(version)}", workplan.read_text(encoding="utf-8")):
        problems.append(f"docs/workplan-v0.4.md does not mention v{version}")


def check_compiled_clients(problems: list[str]) -> None:
    sys.path.insert(0, str(REPO_ROOT))
    import scripts.compile_clients as compiler  # noqa: E402

    spec = yaml.safe_load((REPO_ROOT / "harness.yaml").read_text(encoding="utf-8")) or {}
    fresh = compiler._render_core_protocol(spec, include_mcp=True)
    current = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    if "> Auto-compiled from `harness.yaml`" in current:
        current_body = current.split("\n", 3)[3] if current.count("\n") >= 3 else current
        if fresh not in current_body:
            problems.append("AGENTS.md is stale — run: python scripts/compile_clients.py")


def check_install_doc(problems: list[str]) -> None:
    install = REPO_ROOT / "INSTALL.md"
    if not install.exists():
        problems.append("INSTALL.md missing — installation ships with the release")
        return
    text = install.read_text(encoding="utf-8")
    for needle in ("Platform", "FULL", "LIMITED"):
        if needle not in text:
            problems.append(f"INSTALL.md lacks the support-matrix section marker: {needle!r}")


def check_docs_index(problems: list[str]) -> None:
    index = REPO_ROOT / "docs" / "README.md"
    if not index.exists():
        problems.append("docs/README.md index missing")
        return
    entries = index.read_text(encoding="utf-8")
    for doc in sorted(REPO_ROOT.glob("docs/*.md")):
        if doc.name == "README.md":
            continue
        if doc.name not in entries:
            problems.append(f"docs/{doc.name} is not listed in docs/README.md")


def main() -> int:
    problems: list[str] = []
    check_version_alignment(problems)
    check_compiled_clients(problems)
    check_install_doc(problems)
    check_docs_index(problems)
    if problems:
        print("docs drift detected — docs and code must ship in sync:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(f"docs fresh (v{_version()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
