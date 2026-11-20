"""Deterministic Exit Gate & State-Coupled Anti-Shirking Engine (Python Twin).

Mirrors `extensions/harness-guard.ts` so headless `orchestrator/plan.py` runs,
automated evals (`TC-10` / `TC-11`), and CI scripts enforce the exact same
Zero-Residue & Green-Baseline contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import fnmatch
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any

SHIRKING_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bpre[- ]?existing\b", re.IGNORECASE),
    re.compile(r"\bunrelated to (?:my|these|our) changes?\b", re.IGNORECASE),
    re.compile(r"\bnot introduced by\b", re.IGNORECASE),
    re.compile(r"\bout of scope\b", re.IGNORECASE),
    re.compile(r"\bleft (?:as an exercise|for (?:the )?user)\b", re.IGNORECASE),
    re.compile(r"(不是我引入|原有问题|历史遗留|与本次修改无关|超出本次范围|留给用户|非本次改动导致)"),
]

DEFAULT_RESIDUE_GLOBS = ["*.tmp", "*.bak", "*.orig", "debug_*.py", "scratch_*", "tmp_*"]


@dataclass
class CheckSpec:
    name: str
    command: str
    required: bool = True


@dataclass
class CheckFailure:
    name: str
    exit_code: int
    tail: str


@dataclass
class GateDecision:
    passed: bool
    action: str  # "pass" | "bounce" | "escalate_and_bounce" | "halt_to_user"
    failures: list[CheckFailure] = field(default_factory=list)
    residue_files: list[str] = field(default_factory=list)
    shirking_hits: list[str] = field(default_factory=list)
    fingerprint: str = ""
    retry_count: int = 0
    bounce_prompt: str = ""


def detect_shirking(text: str) -> list[str]:
    hits: list[str] = []
    for rx in SHIRKING_PATTERNS:
        m = rx.search(text or "")
        if m:
            hits.append(m.group(0))
    return hits


def scan_residue_files(repo_dir: Path, residue_globs: list[str] | None = None) -> list[str]:
    globs = residue_globs or DEFAULT_RESIDUE_GLOBS
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            text=True,
        )
        if proc.returncode != 0:
            return []
    except (OSError, subprocess.SubprocessError):
        return []

    hits: list[str] = []
    for raw in proc.stdout.splitlines():
        if not raw.startswith("?? "):
            continue
        rel = raw[3:].strip()
        name = Path(rel).name
        if any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(name, g) for g in globs):
            hits.append(rel)
    return sorted(hits)


_TIMING_RE = re.compile(r"\d+\.\d+s")

def _fingerprint(failures: list[CheckFailure], residue: list[str]) -> str:
    parts = [
        f"{f.name}:{_TIMING_RE.sub('X.Xs', f.tail)[-400:]}"
        for f in failures
    ] + [f"residue:{r}" for r in residue]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]


class ExitGateEngine:
    """Stateful deterministic Exit Gate with anti-shirking and circuit breaker."""

    def __init__(
        self,
        repo_dir: Path,
        checks: list[CheckSpec] | None = None,
        residue_globs: list[str] | None = None,
        max_gate_retries: int = 3,
        command_timeout_sec: int = 60,
    ) -> None:
        self.repo_dir = Path(repo_dir)
        self.checks = checks if checks is not None else []
        self.residue_globs = residue_globs if residue_globs is not None else list(DEFAULT_RESIDUE_GLOBS)
        self.max_gate_retries = max_gate_retries
        self.command_timeout_sec = command_timeout_sec
        self.retry_count = 0
        self.last_fingerprint = ""

    @classmethod
    def from_repo_config(cls, repo_dir: Path) -> "ExitGateEngine":
        cfg_path = Path(repo_dir) / ".pi" / "exit_gate.json"
        if not cfg_path.exists():
            return cls(repo_dir=Path(repo_dir))
        data: dict[str, Any] = json.loads(cfg_path.read_text(encoding="utf-8"))
        checks = [
            CheckSpec(
                name=c["name"],
                command=c["command"],
                required=c.get("required", True),
            )
            for c in data.get("checks", [])
        ]
        return cls(
            repo_dir=Path(repo_dir),
            checks=checks,
            residue_globs=data.get("residue_globs", DEFAULT_RESIDUE_GLOBS),
            max_gate_retries=int(data.get("max_gate_retries", 3)),
            command_timeout_sec=max(5, int(data.get("command_timeout_ms", 60000)) // 1000),
        )

    def evaluate(self, assistant_text: str, mutated_this_turn: bool = True) -> GateDecision:
        if not mutated_this_turn:
            return GateDecision(passed=True, action="pass")

        failures: list[CheckFailure] = []
        for chk in self.checks:
            proc = subprocess.run(
                chk.command,
                cwd=str(self.repo_dir),
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.command_timeout_sec,
                text=True,
            )
            if proc.returncode != 0 and chk.required:
                combined = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
                tail = "\n".join(combined.splitlines()[-25:])
                failures.append(CheckFailure(name=chk.name, exit_code=proc.returncode, tail=tail))

        residue = scan_residue_files(self.repo_dir, self.residue_globs)

        if not failures and not residue:
            self.retry_count = 0
            self.last_fingerprint = ""
            return GateDecision(passed=True, action="pass")

        fp = _fingerprint(failures, residue)
        repeated = fp == self.last_fingerprint
        self.last_fingerprint = fp

        # State-coupled: only flag shirking when the repo is actually red or dirty!
        shirking_hits = detect_shirking(assistant_text)

        if self.retry_count >= self.max_gate_retries:
            return GateDecision(
                passed=False,
                action="halt_to_user",
                failures=failures,
                residue_files=residue,
                shirking_hits=shirking_hits,
                fingerprint=fp,
                retry_count=self.retry_count,
            )

        self.retry_count += 1
        action = "escalate_and_bounce" if repeated else "bounce"
        lines = [
            f"[HARNESS_EXIT_GATE_RETRY] Attempt {self.retry_count}/{self.max_gate_retries} (fingerprint={fp})."
        ]
        if shirking_hits:
            lines.append(
                f"[ANTI_SHIRKING_INTERCEPT] Detected buck-passing phrasing ({', '.join(shirking_hits)}) "
                f"while verification is red. Fix blocking failures instead of dismissing them."
            )
        if repeated:
            lines.append("[ESCALATE_REASONING: high] Identical error repeated; re-analyze root cause.")
        for f in failures:
            lines.append(f"Failed check `{f.name}` (exit={f.exit_code}):\n{f.tail}")
        if residue:
            lines.append("Leftover residue files to remove: " + ", ".join(residue))

        return GateDecision(
            passed=False,
            action=action,
            failures=failures,
            residue_files=residue,
            shirking_hits=shirking_hits,
            fingerprint=fp,
            retry_count=self.retry_count,
            bounce_prompt="\n".join(lines),
        )
