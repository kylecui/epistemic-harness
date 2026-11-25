"""Read-only tool surface for tooled sub-agents (G13).

The middle tier between text-only sub-agents (no tools at all) and full
`dispatch_tooled` (a host pi process that can write and run anything): an
explorer that can LOOK but cannot touch. Every tool is sandboxed to a declared
workdir root; path escape is rejected before any filesystem call.

Tools: read_file / list_dir / grep (python regex walk, no shell). Nothing here
can write, delete, or execute.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache"}
MAX_FILE_BYTES = 1_000_000
MAX_GREP_MATCHES = 50


class SandboxError(ValueError):
    """Raised when a path escapes the declared workdir root."""


def _resolve(root: Path, rel: str) -> Path:
    target = (root / (rel or ".")).resolve()
    root_resolved = root.resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise SandboxError(f"path escapes workdir: {rel!r}")
    return target


def read_file(root: Path, rel: str, max_chars: int = 8000) -> str:
    path = _resolve(root, rel)
    if not path.is_file():
        return f"ERROR: not a file: {rel}"
    raw = path.read_bytes()
    if len(raw) > MAX_FILE_BYTES:
        return f"ERROR: file too large ({len(raw)} bytes > {MAX_FILE_BYTES}); narrow with grep"
    text = raw.decode("utf-8", errors="replace")
    if len(text) > max_chars:
        return text[:max_chars] + f"\n...[truncated at {max_chars} chars]"
    return text


def list_dir(root: Path, rel: str = "", max_entries: int = 200) -> str:
    path = _resolve(root, rel or ".")
    if not path.is_dir():
        return f"ERROR: not a directory: {rel or '.'}"
    lines: list[str] = []
    count = 0
    # Issue #24: a transient mount error (ENOMEM/EIO/ESTALE) is retried once by with_retry;
    # a genuinely missing directory still fails immediately.
    from orchestrator.fsretry import with_retry
    for entry in with_retry(lambda: sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))):
        if count >= max_entries:
            lines.append(f"...[truncated at {max_entries} entries]")
            break
        suffix = "/" if entry.is_dir() else ""
        lines.append(entry.name + suffix)
        count += 1
    return "\n".join(lines)


def grep(root: Path, pattern: str, rel: str = "", max_matches: int = MAX_GREP_MATCHES) -> str:
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        return f"ERROR: invalid regex: {exc}"
    start = _resolve(root, rel or ".")
    matches: list[str] = []
    for base in ([start] if start.is_file() else [start]):
        if base.is_file():
            candidates = [base]
        else:
            candidates = []
            for path in sorted(base.rglob("*")):
                if any(part in SKIP_DIRS for part in path.parts):
                    continue
                if path.is_file() and path.stat().st_size <= MAX_FILE_BYTES:
                    candidates.append(path)
        for path in candidates:
            try:
                text = path.read_bytes().decode("utf-8", errors="replace")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    matches.append(f"{path.relative_to(root.resolve()).as_posix()}:{lineno}: {line.strip()[:200]}")
                    if len(matches) >= max_matches:
                        matches.append(f"...[truncated at {max_matches} matches]")
                        return "\n".join(matches)
    if not matches:
        return "(no matches)"
    return "\n".join(matches)


TOOLS: dict[str, Any] = {
    "read_file": read_file,
    "list_dir": list_dir,
    "grep": grep,
}

TOOL_SPECS = [
    {"name": "read_file", "args": {"path": "str (relative to workdir)", "max_chars": "int, optional"},
     "returns": "file text, truncated at max_chars"},
    {"name": "list_dir", "args": {"path": "str, optional"}, "returns": "directory listing, dirs first"},
    {"name": "grep", "args": {"pattern": "python regex", "path": "str, optional"},
     "returns": "file:line: text matches, capped"},
]


def execute_tool(root: Path, name: str, args: dict[str, Any]) -> str:
    fn = TOOLS.get(name)
    if fn is None:
        return f"ERROR: unknown tool {name!r}; available: {', '.join(TOOLS)}"
    try:
        if name == "read_file":
            return read_file(root, str(args.get("path") or ""), int(args.get("max_chars") or 8000))
        if name == "list_dir":
            return list_dir(root, str(args.get("path") or ""))
        return grep(root, str(args.get("pattern") or ""), str(args.get("path") or ""))
    except SandboxError as exc:
        return f"ERROR: {exc}"
