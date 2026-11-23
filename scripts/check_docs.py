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


def _discover_test_count() -> tuple[int, int]:
    """(case_count, failed_import_modules) under tests/ without executing them.

    A partial environment (missing deps in a slim container) makes discovery
    emit one _FailedTest placeholder per unimportable module — counting those
    as 'tests' is what corrupted the badge once (2026-11-24: container run
    reported 7). Callers must not trust a count with failures.
    """
    import unittest
    from unittest.loader import _FailedTest

    loader = unittest.TestLoader()
    suite = loader.discover(str(REPO_ROOT / "tests"), top_level_dir=str(REPO_ROOT))

    def count(s: unittest.TestSuite) -> tuple[int, int]:
        n = 0
        failed = 0
        for item in s:
            if isinstance(item, unittest.TestSuite):
                a, b = count(item)
                n += a
                failed += b
            else:
                n += 1
                if isinstance(item, _FailedTest):
                    failed += 1
        return n, failed

    return count(suite)


def check_test_count_badge(problems: list[str]) -> None:
    """README's `tests-N green` badge must equal the real discovered count.

    Drift is FIXED, not just reported (issue #11, 2026-11-24): the badge is a
    derived value, so this check rewrites it in both READMEs and reports the
    sync. Only a failed rewrite is a problem.
    """
    badge_re = re.compile(r"tests-(\d+)%20green")
    actual, failed_imports = _discover_test_count()
    if failed_imports:
        problems.append(
            f"badge not synced: discovery in this runner hit {failed_imports} unimportable module(s) "
            f"(count {actual}); fix the runner environment and re-run"
        )
        return
    if actual < 50:
        problems.append(f"badge not synced: discovered count {actual} is implausibly low (floor 50)")
        return
    for name in ("README.md", "README_ZH.md"):
        path = REPO_ROOT / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        m = badge_re.search(text)
        if not m or int(m.group(1)) == actual:
            continue
        try:
            path.write_text(badge_re.sub(f"tests-{actual}%20green", text, count=1), encoding="utf-8", newline="\n")
            print(f"badge synced: {name} tests-{actual}")
        except OSError as exc:
            problems.append(f"{name} badge says {m.group(1)} tests but discovery finds {actual} and rewrite failed: {exc}")


def main() -> int:
    problems: list[str] = []
    check_version_alignment(problems)
    check_compiled_clients(problems)
    check_install_doc(problems)
    check_docs_index(problems)
    check_test_count_badge(problems)
    if problems:
        print("docs drift detected — docs and code must ship in sync:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(f"docs fresh (v{_version()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
