"""Deterministic Exit Gate & State-Coupled Anti-Shirking Engine (Python Twin).

Mirrors `extensions/harness-guard.ts` so headless `orchestrator/plan.py` runs,
automated evals (`TC-10` / `TC-11`), and CI scripts enforce the exact same
Zero-Residue & Green-Baseline contract.

Also mirrors the review-turn contract checks from
`proxy_gateway/response_guard.py` (issue #1): a review turn that declares a
defect must ship a complete remediation plan (acceptance criteria + rollback),
and structured outputs must not silently promote L3-derived conclusions.
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

# ---------------------------------------------------------------------------
# Review-turn contract checks (mirror of proxy_gateway/response_guard.py)
# ---------------------------------------------------------------------------

_DEFECT_ITEM_RE = re.compile(
    r"(?:\bP[1-9]\d?\b|缺陷\s*#?[1-9]\d?|缺口\s*#?[1-9]\d?|问题\s*#?[1-9]\d?|"
    r"\bdefect\s*#?[1-9]\d?|\bissue\s*#?[1-9]\d?)",
    re.I,
)
_ACCEPTANCE_RE = re.compile(r"(验收|acceptance)", re.I)
_ROLLBACK_RE = re.compile(r"(回退|回滚|rollback|恢复路径)", re.I)
_DOWNGRADE_RE = re.compile(
    r"(最小后续动作|minimal next (?:actions|steps)|补一段文档|补充文档|写进已知问题|"
    r"记为已知问题|记入已知问题|留待观察|defer(?:red)? to)",
    re.I,
)
_L4_TRADEOFF_RE = re.compile(
    r"(本次只出评审结论|只要评审结论|只出评审结论|只列\s*file:line|只记录\s*file:line|"
    r"不需要修复方案|暂不修复|review[- ]only|no fix (?:needed|required))",
    re.I,
)
_HEADER_CAP_RE = re.compile(r"Confidence Cap:\s*(L[1-5])", re.I)
_BODY_LAYER_RE = re.compile(r"\[L([1-5])\b")
_L3_TAG_RE = re.compile(r"\[L3\b")
_L3_SCOPE_RE = re.compile(r"(适用|scope|适用范围)", re.I)
_L3_COUNTER_RE = re.compile(r"(反例|counter[- ]?example|失效)", re.I)
_SECTION_CORE_RE = re.compile(r"(核心结论|core conclusion)", re.I)
_SECTION_BREAKDOWN_RE = re.compile(r"(认识论分解|epistemic breakdown|依据分层)", re.I)
_SECTION_GAPS_RE = re.compile(r"(证据缺口|evidence gap)", re.I)


def _defect_items(text: str) -> list[tuple[str, str]]:
    matches = list(_DEFECT_ITEM_RE.finditer(text))
    items: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        items.append((m.group(0), text[m.start():end]))
    return items


def check_remediation_completeness(text: str) -> list[str]:
    """Declared defects must ship a complete fix plan (issue #1).

    No defect anchors -> not a defect-review turn -> pass. An explicit L4
    trade-off cited in the reply (review-only request) -> pass.
    """
    if not text or not text.strip():
        return []
    items = _defect_items(text)
    if not items:
        return []
    if _L4_TRADEOFF_RE.search(text):
        return []
    violations: list[str] = []
    for label, segment in items:
        if not _ACCEPTANCE_RE.search(segment):
            violations.append(f"{label}: 已声明缺陷但缺少验收判据 (验收/acceptance)")
        if not _ROLLBACK_RE.search(segment):
            violations.append(f"{label}: 已声明缺陷但缺少回退路径 (回退/rollback)")
    downgrade = _DOWNGRADE_RE.search(text)
    if downgrade:
        violations.append(
            f"缺陷降级: '{downgrade.group(0)}' 与已声明缺陷同现; "
            f"缺陷必须给出完整修复方案(改动点/迁移影响/回退/验收), "
            f"除非显式引用 L4 运营决策依据"
        )
    return violations


def check_silent_promotion(text: str) -> list[str]:
    """Header Confidence Cap must not be stronger than the weakest body layer."""
    m = _HEADER_CAP_RE.search(text or "")
    layers = [int(n) for n in _BODY_LAYER_RE.findall(text or "")]
    if not m or not layers:
        return []
    cap, body = int(m.group(1)[1]), max(layers)
    if cap < body:
        return [
            f"silent promotion: 头部 Confidence Cap L{cap} 弱于正文最弱依据 L{body} "
            f"(代码推演/经验判断封顶 L{body})"
        ]
    return []


def check_l3_scope(text: str) -> list[str]:
    """Each `[L3` label needs scope + counter-example anchors within 3 lines."""
    lines = (text or "").splitlines()
    violations: list[str] = []
    for idx, line in enumerate(lines):
        for _m in _L3_TAG_RE.finditer(line):
            window = "\n".join(lines[idx:idx + 3])
            missing = []
            if not _L3_SCOPE_RE.search(window):
                missing.append("适用/scope")
            if not _L3_COUNTER_RE.search(window):
                missing.append("反例/counter-example")
            if missing:
                violations.append(f"[L3] 标签(第{idx + 1}行)后 3 行内缺少: {', '.join(missing)}")
    return violations


def check_review_completeness(text: str) -> list[str]:
    """Union of review-turn contract checks. Empty means compliant."""
    return (
        check_remediation_completeness(text)
        + check_silent_promotion(text)
        + check_l3_scope(text)
    )


def build_review_intercept(violations: list[str], *, retry: bool) -> str:
    lines = [
        "[REVIEW_CONTRACT_INTERCEPT] 评审回合契约违规:",
        *[f"  - {v}" for v in violations],
    ]
    if retry:
        lines.append(
            "请按契约重做本回合: 已声明缺陷必须给出完整修复方案 "
            "(改动点/迁移影响/回退路径/可证伪验收判据), Confidence Cap 不得高于"
            "正文最弱依据层, 每个 [L3] 附适用范围与反例。"
        )
    else:
        lines.append("[ESCALATE_TO_L2] 重试后仍违规, 按 L2 上报人工复核, 不得再次自动打回。")
    return "\n".join(lines)


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
    contract_violations: list[str] = field(default_factory=list)
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
        self.review_retry_count = 0

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
            # Review turn (zero file changes): the file/residue gate stays off,
            # but a declared defect must still ship a complete remediation plan
            # (issue #1). Bounce at most once, then escalate to an L2 report.
            violations = check_review_completeness(assistant_text)
            if not violations:
                self.review_retry_count = 0
                return GateDecision(passed=True, action="pass")
            if self.review_retry_count >= 1:
                return GateDecision(
                    passed=False,
                    action="halt_to_user",
                    contract_violations=violations,
                    retry_count=self.review_retry_count,
                    bounce_prompt=build_review_intercept(violations, retry=False),
                )
            self.review_retry_count += 1
            return GateDecision(
                passed=False,
                action="bounce",
                contract_violations=violations,
                retry_count=self.review_retry_count,
                bounce_prompt=build_review_intercept(violations, retry=True),
            )

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
            self.review_retry_count = 0
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
