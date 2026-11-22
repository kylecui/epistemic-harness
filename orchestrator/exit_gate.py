"""Deterministic Exit Gate & State-Coupled Anti-Shirking Engine (Python Twin).

Mirrors `extensions/harness-guard.ts` so headless `orchestrator/plan.py` runs,
automated evals (`TC-10` / `TC-11`), and CI scripts enforce the exact same
Zero-Residue & Green-Baseline contract.

Also mirrors the review-turn contract checks from
`proxy_gateway/response_guard.py` (issue #1): a review turn that declares a
defect must ship a complete remediation plan (acceptance criteria + rollback),
and structured outputs must not silently promote L3-derived conclusions.

Verification contract (issue #2):
  * a green verdict requires at least one check that actually executed;
  * `run_gate(claims=[...], verification_commands=[...])` binds quantified
    claims to evidence the gate produced itself;
  * `.pi/exit_gate.json` commands MUST be shell-agnostic: on Windows the gate
    may be launched with `cmd.exe` or with a POSIX shell depending on the host
    environment, so no `printf`, no `;` chaining, no bash-only builtins;
  * a launcher failure (OSError/timeout) is retried once and reported as
    `EXEC_ERROR:`, because that is an environment fault, not a code defect.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import fnmatch
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

try:  # normal package import
    from orchestrator.task_contract import (
        TaskContract,
        load as load_task_contract,
        unclosed as unclosed_predicates,
    )
except ImportError:  # loaded standalone via importlib (tests)
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from orchestrator.task_contract import (
        TaskContract,
        load as load_task_contract,
        unclosed as unclosed_predicates,
    )

SHIRKING_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bpre[- ]?existing\b", re.IGNORECASE),
    re.compile(r"\bunrelated to (?:my|these|our) changes?\b", re.IGNORECASE),
    re.compile(r"\bnot introduced by\b", re.IGNORECASE),
    re.compile(r"\bout of scope\b", re.IGNORECASE),
    re.compile(r"\bleft (?:as an exercise|for (?:the )?user)\b", re.IGNORECASE),
    re.compile(r"(不是我引入|原有问题|历史遗留|与本次修改无关|超出本次范围|留给用户|非本次改动导致)"),
]

DEFAULT_RESIDUE_GLOBS = [
    "*.tmp", "*.bak", "*.orig", "debug_*.py", "scratch_*", "tmp_*",
    # dotfile scratch (e.g. `.tmp_omo.md` found in repo root 2026-11-22): the
    # plain `tmp_*` glob does NOT match a leading-dot name under fnmatch rules
    # (`.*.tmp*` needs two dots; `.tmp_omo.md` has one).
    ".*tmp*", ".*scratch*", ".*debug*", ".*.bak", ".*.orig",
]

# ---------------------------------------------------------------------------
# Review-turn contract checks (mirror of proxy_gateway/response_guard.py)
# ---------------------------------------------------------------------------

_DEFECT_ITEM_RE = re.compile(
    # 'P1' style anchors must not fire on version/milestone numbers like
    # 'P1.6' or 'P12.3' (live false positive 2026-11-22: a progress header
    # 'P1.6 完成' was read as a declared defect item).
    r"(?:\bP[1-9]\d?(?![.\d])\b|缺陷\s*#?[1-9]\d?|缺口\s*#?[1-9]\d?|问题\s*#?[1-9]\d?|"
    r"\bdefect\s*#?[1-9]\d?|\bissue\s*#?[1-9]\d?)",
    re.I,
)
_ACCEPTANCE_RE = re.compile(r"(验收|acceptance)", re.I)
_ROLLBACK_RE = re.compile(r"(回退|回滚|rollback|恢复路径)", re.I)

# --- Substance checks (2026-11-22 review, defect #2; mirror of
# proxy_gateway/response_guard.py — keep the two in sync) --------------------
_FILLER_RE = re.compile(
    r"(各种情况|视情况(?:而定)?|具体情况|都有可能|某些情况|有时候|部分情况|"
    r"因情况而异|都有可能|不好说|不一定|不适用|not applicable|\bn/?a\b)",
    re.I,
)
_FALSIFIABLE_RE = re.compile(
    r"(\d|exit\s*0|assert|断言|单测|单元测试|集成测试|unittest|pytest|green|"
    r"为零|0\s*条|不通过|相等|一致|match|curl|命令|复现失败|计数)",
    re.I,
)
_ROLLBACK_CONCRETE_RE = re.compile(
    r"(git|快照|备份|开关|feature flag|revert|镜像|上一版本|恢复原|回滚到|"
    r"回滚迁移|迁移回滚|命令|脚本|备份文件|重新部署)",
    re.I,
)
_CJK_RUN = re.compile(r"[一-鿿]+")
_STRUCTURED_BLOCK_RE = re.compile(r"```harness-claim\s*\n(.*?)```", re.S)
_STRUCT_REQUIRED_FIELDS = ("defect", "fix_points", "rollback", "acceptance")


def _substantive(text: str, min_cjk_chars: int = 3) -> bool:
    cleaned = _FILLER_RE.sub(" ", text or "")
    return sum(len(m.group(0)) for m in _CJK_RUN.finditer(cleaned)) >= min_cjk_chars


def _anchor_substantive(window: str, anchor_re: "re.Pattern[str]") -> bool:
    # Mirror of response_guard._anchor_substantive: substance is judged on the
    # anchor's own line only, so a neighbouring section cannot lend weight to
    # a filler phrase like '适用: 各种情况'.
    m = anchor_re.search(window or "")
    if not m:
        return False
    rest = window[m.end():].split("\n", 1)[0]
    return _substantive(rest[:60])


def _validate_structured_claims(text: str) -> tuple[list[dict], list[str]]:
    """Parse and validate ```harness-claim JSON blocks (mirror of response_guard)."""
    import json as _json

    claims: list[dict] = []
    violations: list[str] = []
    for block_idx, m in enumerate(_STRUCTURED_BLOCK_RE.finditer(text or "")):
        raw = m.group(1).strip()
        try:
            data = _json.loads(raw)
        except ValueError as exc:
            violations.append(f"harness-claim 块 #{block_idx + 1}: JSON 解析失败 ({exc})")
            continue
        items = data if isinstance(data, list) else [data]
        for item_idx, item in enumerate(items):
            label = f"harness-claim #{block_idx + 1}.{item_idx + 1}"
            if not isinstance(item, dict):
                violations.append(f"{label}: 必须是 JSON object")
                continue
            for field in _STRUCT_REQUIRED_FIELDS:
                value = str(item.get(field, "") or "")
                if not value.strip():
                    violations.append(f"{label}: 字段 '{field}' 为空")
                elif field == "acceptance" and not _FALSIFIABLE_RE.search(value):
                    violations.append(f"{label}: acceptance 缺少可证伪判据 (数字/测试命令/断言)")
                elif field == "rollback" and not (
                    _ROLLBACK_CONCRETE_RE.search(value) and _substantive(value, min_cjk_chars=2)
                ):
                    violations.append(f"{label}: rollback 缺少具体机制 (git/快照/开关/命令)")
                elif field in ("defect", "fix_points") and not _substantive(value, min_cjk_chars=4):
                    violations.append(f"{label}: 字段 '{field}' 内容过短或为样板话")
            claims.append(item)
    return claims, violations
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
    structured_claims, structured_violations = _validate_structured_claims(text)
    if structured_claims:
        # Structured path chosen: prose anchor checks waived; schema violations only.
        return structured_violations
    if not items:
        return structured_violations
    if _L4_TRADEOFF_RE.search(text):
        return []
    violations: list[str] = list(structured_violations)
    for label, segment in items:
        acc_match = _ACCEPTANCE_RE.search(segment)
        if not acc_match:
            violations.append(f"{label}: 已声明缺陷但缺少验收判据 (验收/acceptance)")
        else:
            # Mirror of response_guard: scan the criterion itself, not the whole
            # segment — the item label's digit ("缺陷1") must not count as the
            # falsifiable number.
            acc_rest = segment[acc_match.end():acc_match.end() + 80]
            if not _FALSIFIABLE_RE.search(acc_rest):
                violations.append(
                    f"{label}: 验收判据不可证伪 (需数字/测试命令/断言, 而非 '测试通过即可')"
                )
        rb_match = _ROLLBACK_RE.search(segment)
        if not rb_match:
            violations.append(f"{label}: 已声明缺陷但缺少回退路径 (回退/rollback)")
        else:
            rb_rest = segment[rb_match.end():rb_match.end() + 80]
            if not (
                _ROLLBACK_CONCRETE_RE.search(rb_rest)
                and _substantive(rb_rest, min_cjk_chars=2)
            ):
                violations.append(
                    f"{label}: 回退路径不具体 (需命名机制: git/快照/开关/命令, 而非 '可回退')"
                )
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
            if not _anchor_substantive(window, _L3_SCOPE_RE):
                missing.append("适用/scope")
            if not _anchor_substantive(window, _L3_COUNTER_RE):
                missing.append("反例/counter-example")
            if missing:
                violations.append(f"[L3] 标签(第{idx + 1}行)后 3 行内缺少: {', '.join(missing)}")
    return violations


# ---------------------------------------------------------------------------
# Underdetermination guard (issue #3)
# ---------------------------------------------------------------------------

_DECISION_ASK_RE = re.compile(
    r"(需要你(?:来)?(?:决定|拍板|裁量|定夺|选)|请你(?:决定|拍板|裁量|确认)|需要(?:你)?确认|"
    r"待你决策|由你决定|决策点|需要裁量|decision needed|need your (?:decision|call))",
    re.I,
)
_L4_ANCHOR_RE = re.compile(
    r"(\bL4\b|预算|工期|人力|团队|风险取舍|产品取舍|商业取舍|合规要求|"
    r"budget|headcount|timeline|risk trade|product trade)",
    re.I,
)
_L2_GAP_ANCHOR_RE = re.compile(
    r"(缺(?:少|失)?(?:L2|证据|数据|日志|凭据|文档)|没有(?:可核查|可验证|一手)|"
    r"L2\s*缺失|未检索|需外部检索|evidence gap)",
    re.I,
)

# ---------------------------------------------------------------------------
# External grounding for selection / SOTA claims (research discipline)
# ---------------------------------------------------------------------------

_SOTA_CLAIM_RE = re.compile(
    r"(\bSOTA\b|state[- ]of[- ]the[- ]art|最佳方案|最优方案|最流行|主流方案|业界标准|"
    r"公认做法|普遍做法|best[- ]in[- ]class|de[- ]facto standard)",
    re.I,
)
_SOURCE_ANCHOR_RE = re.compile(
    r"(https?://|arxiv[:\s]|doi[:\s]|github\.com/|huggingface\.co/|"
    r"检索于|accessed\s+\d{4}|\b(?:19|20)\d{2}-\d{2}-\d{2}\b|RFC\s?\d+)",
    re.I,
)
_NOT_SEARCHED_RE = re.compile(
    r"(未检索|未做外部检索|凭记忆|from memory|without (?:an )?external search|no external search)",
    re.I,
)
_FENCE_RE = re.compile(r"```.*?```", re.S)


def _strip_noise(text: str) -> list[str]:
    """Drop fenced code and blockquoted lines so quoted material cannot trip the checks."""
    text = _FENCE_RE.sub("\n", text or "")
    return [ln for ln in text.splitlines() if not ln.lstrip().startswith(">")]


def check_underdetermination(text: str) -> list[str]:
    """A raised decision point must be genuinely underdetermined (issue #3).

    Every explicit ask anchor ("需要你拍板" / "请确认" / "决策点") needs, within
    the next 3 lines, either an L4 trade-off anchor (budget/risk/team/product)
    or a missing-L2 anchor. Otherwise the reply is asking the user to decide
    something already closed by definition or by evidence.
    """
    lines = _strip_noise(text)
    violations: list[str] = []
    for idx, line in enumerate(lines):
        for m in _DECISION_ASK_RE.finditer(line):
            window = "\n".join(lines[idx:idx + 3])
            if _L4_ANCHOR_RE.search(window) or _L2_GAP_ANCHOR_RE.search(window):
                continue
            violations.append(
                f"伪决策点(第{idx + 1}行) '{m.group(0)}': 未标明触发层; "
                f"若不问时答案唯一(定义/证据已闭合)直接给结论, 确需裁量请注明 L4 取舍或缺失的 L2 证据"
            )
    return violations


def check_external_grounding(text: str) -> list[str]:
    """SOTA/superlative claims need an external source anchor or an explicit

    "no search done" declaration. Keeps recommendation-heavy answers from being
    asserted purely from memory.
    """
    body = "\n".join(_strip_noise(text))
    m = _SOTA_CLAIM_RE.search(body)
    if not m:
        return []
    if _SOURCE_ANCHOR_RE.search(body) or _NOT_SEARCHED_RE.search(body):
        return []
    return [
        f"选型/最优性断言 '{m.group(0)}' 缺少来源锚点(URL/arXiv/DOI/检索日期); "
        f"若本回合未做外部检索, 请显式写明并据实下调置信上限"
    ]


def check_review_completeness(text: str) -> list[str]:
    """Union of review-turn contract checks. Empty means compliant."""
    return (
        check_remediation_completeness(text)
        + check_silent_promotion(text)
        + check_l3_scope(text)
        + check_underdetermination(text)
        + check_external_grounding(text)
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
    runner: str | None = None  # None = inherit gate_runner (auto|docker|host)


@dataclass
class Evidence:
    """One executed verification with its machine-checked outcome."""

    name: str
    command: str
    exit_code: int
    source: str = "config"  # "config" | "caller"
    tail: str = ""
    counted: int | None = None
    stdout_lines: int = 0
    runner: str = "host"  # "host" | "docker" — a green verdict must name its shell
    elapsed: float = 0.0  # wall-clock seconds this verification actually took (G7)


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
    verdict: str = "green"  # green|red|no_evidence|unbound_claim|unclosed_predicate
    evidence: list[Evidence] = field(default_factory=list)
    unbound_claims: list[str] = field(default_factory=list)
    claim_errors: list[str] = field(default_factory=list)
    failure_classes: list[dict[str, Any]] = field(default_factory=list)
    unclosed_predicates: list[dict[str, Any]] = field(default_factory=list)
    verifier_hash: str = ""
    verifier_changed: list[str] = field(default_factory=list)
    memory_refs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    loop_repeat_count: int = 0
    escalate_root_cause: bool = False
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


# ---------------------------------------------------------------------------
# Issue #2 — quantified / completeness claims must bind to executed evidence
# ---------------------------------------------------------------------------

QUANT_CLAIM_RE = re.compile(
    r"(\d{1,3}(?:\.\d+)?\s*%|\ball\b|\bzero\b|\bnone missing\b|\bfull coverage\b|"
    r"全部|所有|无遗漏|无缺失|零残留|全覆盖|完整覆盖|均已完成|均已覆盖|不含遗漏)",
    re.I,
)
CLAIM_QUALIFIER_RE = re.compile(
    r"(未验证|未校验|未检查|仅抽样|抽样\s*\d+|其余未验证|部分验证|"
    r"not verified|unverified|sampled only|partial(?:ly)? (?:checked|verified))",
    re.I,
)
_ENUMERATION_RE = re.compile(r"(项|条|个|处|页|文件|接口|用例|用例)")


def extract_unbound_claims(text: str, declared: list[str] | None = None) -> list[str]:
    """Return quantified/completeness claim snippets with no bound check.

    A snippet is exempt when it carries an explicit limitation qualifier
    ("仅抽样 5 页，其余未验证"), sits inside fenced code, or its text is
    declared in the caller's `claims` mapping.
    """
    declared_norm = [" ".join(d.lower().split()) for d in (declared or []) if d]
    snippets: list[str] = []
    body = _FENCE_RE.sub("\n", text or "")
    for raw in re.split(r"(?<=[。！？；\n])|(?<=[.!?]\s)", body):
        line = raw.strip()
        if not line or not QUANT_CLAIM_RE.search(line):
            continue
        if CLAIM_QUALIFIER_RE.search(line):
            continue
        norm = " ".join(line.lower().split())
        if any(d in norm or norm in d for d in declared_norm):
            continue
        snippets.append(line[:160])
    return snippets


def classify_failures(
    failures: list["CheckFailure"], claim_errors: list[str], evidence: list["Evidence"]
) -> list[dict[str, Any]]:
    """Give every failure an owner (G2): code / check / environment / root cause.

    Without an owner, a loop can only retry blindly. Each class carries the default
    next action, so the bounce prompt can say what to do instead of "fix it".
    """
    out: list[dict[str, Any]] = []
    for f in failures:
        tail = (f.tail or "")
        if "RUNNER_UNAVAILABLE" in tail:
            cls, action = "env_missing", "build/pull the runner image or switch gate_runner to host"
        elif "EXEC_ERROR" in tail:
            cls, action = "env_missing", "retry once; if it persists the command cannot start on this host"
        elif f.name.startswith("claim-count:"):
            cls, action = "check_defect", "the claim and the check disagree: fix the count, the claim, or the check"
        elif any(k in tail for k in ("ModuleNotFoundError", "ImportError", "command not found",
                                     "is not recognized")):
            cls, action = "env_missing", "install the missing dependency or run through scripts/verify.py"
        else:
            cls, action = "code_defect", "fix the code path that the failing check exercises"
        out.append({"name": f.name, "class": cls, "action": action})
    for _err in claim_errors:
        out.append({"name": "claim-binding", "class": "underdetermined",
                    "action": "declare the check the claim binds to, or qualify the claim"})
    if not out and not evidence:
        out.append({"name": "evidence", "class": "underdetermined",
                    "action": "add checks to .pi/exit_gate.json or pass verification_commands"})
    return out


VERIFIER_PATHS = (".pi/exit_gate.json", "scripts/verify.py", "scripts/check_eol.py")


def verifier_fingerprint(repo_dir: Path) -> str:
    """Hash the verifier itself (G4): config + gate scripts + the test tree.

    A green run whose verifier changed since the last red run is the tamper
    signal: it must be visible in the verdict instead of silently passing.
    """
    repo = Path(repo_dir)
    digest = hashlib.sha256()
    for rel in VERIFIER_PATHS:
        path = repo / rel
        if path.exists():
            digest.update(rel.encode("utf-8"))
            digest.update(path.read_bytes())
    tests_dir = repo / "tests"
    if tests_dir.is_dir():
        for path in sorted(tests_dir.glob("*.py")):
            digest.update(path.name.encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def verifier_change_warnings(ledger_path: Path, current: str, window: int = 20) -> list[str]:
    """Warn when the verifier changed after a red run in the recent ledger."""
    try:
        if not ledger_path.exists() or not current:
            return []
        records = [json.loads(l) for l in ledger_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    except (OSError, json.JSONDecodeError):
        return []
    for rec in reversed(records[-window:]):
        if rec.get("kind") != "gate" or rec.get("verdict") == "green":
            continue
        prev = rec.get("verifier")
        if prev and prev != current:
            return [
                f"verifier_changed: 上一次红判定时校验器指纹为 {prev}, 现在是 {current}; "
                f"确认改动是修检查而不是绕过检查"
            ]
    return []


def _normalize_evidence_specs(specs: Any) -> list[CheckSpec]:
    if not specs:
        return []
    out: list[CheckSpec] = []
    if isinstance(specs, (str, dict)):
        specs = [specs]
    for i, item in enumerate(specs):
        if isinstance(item, str):
            out.append(CheckSpec(name=f"verify-{i + 1}", command=item))
        elif isinstance(item, dict) and item.get("command"):
            out.append(CheckSpec(name=str(item.get("name") or f"verify-{i + 1}"),
                                 command=str(item["command"])))
    return out


def _validate_claims(
    claims: list[dict[str, Any]] | None, evidence: list[Evidence]
) -> tuple[list[str], list[CheckFailure]]:
    """Bind declared claims to actually executed checks; also verify count coverage."""
    errors: list[str] = []
    failures: list[CheckFailure] = []
    memory_refs: list[str] = []
    by_name = {e.name: e for e in evidence}
    for i, claim in enumerate(claims or []):
        if not isinstance(claim, dict) or not claim.get("text"):
            errors.append(f"claims[{i}]: 缺少 text")
            continue
        if claim.get("memory_refs"):
            memory_refs.extend(str(m) for m in claim["memory_refs"])
        check = str(claim.get("check") or "")
        if not check:
            errors.append(f"claims[{i}] '{claim['text'][:40]}': 缺少 check (必须指名已执行的校验)")
            continue
        ev = by_name.get(check)
        if ev is None:
            errors.append(
                f"claims[{i}] '{claim['text'][:40]}': check '{check}' 本回合未执行; "
                f"已执行: {', '.join(by_name) or '(none)'}"
            )
            continue
        expected = claim.get("expected_count")
        if expected is not None and ev.counted is not None:
            if int(expected) != int(ev.counted):
                failures.append(
                    CheckFailure(
                        name=f"claim-count:{check}",
                        exit_code=1,
                        tail=f"断言 '{claim['text'][:40]}' 声称 {expected} 项, 校验输出实为 {ev.counted} 项",
                    )
                )
    return errors, failures, memory_refs


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
        evidence_policy: str = "warn",
        ledger_path: Path | None = None,
        gate_runner: str = "host",
        verify_image: str = "epistemic-verify:local",
    ) -> None:
        self.repo_dir = Path(repo_dir)
        self.checks = checks if checks is not None else []
        self.residue_globs = residue_globs if residue_globs is not None else list(DEFAULT_RESIDUE_GLOBS)
        self.max_gate_retries = max_gate_retries
        self.command_timeout_sec = command_timeout_sec
        self.evidence_policy = evidence_policy
        self.gate_runner = gate_runner
        self.verify_image = verify_image
        self._runner_cache: dict[str, tuple[bool, str]] = {}
        self.ledger_path = Path(ledger_path) if ledger_path else (self.repo_dir / ".pi" / "loop_ledger.jsonl")
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
            evidence_policy=str(data.get("evidence_policy", "warn")),
            gate_runner=str(data.get("gate_runner", "host")),
            verify_image=str(data.get("verify_image", "epistemic-verify:local")),
        )

    # -- evidence execution ------------------------------------------------

    def _runner_ready(self, name: str) -> tuple[bool, str]:
        """Is this runner usable here? Cached per engine instance.

        `auto` must be decidable without side effects, so it checks the docker CLI
        and whether the verify image already exists. A missing image is not
        silently built: building inside a gate run would hide minutes of work.
        """
        if name in self._runner_cache:
            return self._runner_cache[name]
        ok, reason = False, "unknown runner"
        if name == "host":
            ok, reason = True, "host shell"
        elif name == "docker":
            if not shutil.which("docker"):
                ok, reason = False, "docker CLI not found on PATH"
            else:
                try:
                    probe = subprocess.run(
                        ["docker", "image", "inspect", self.verify_image],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20,
                    )
                    ok = probe.returncode == 0
                    reason = "ok" if ok else (
                        f"image {self.verify_image} not built "
                        f"(docker build -f Dockerfile.verify -t {self.verify_image} .)"
                    )
                except (OSError, subprocess.SubprocessError) as exc:
                    ok, reason = False, f"docker unusable: {exc}"
        self._runner_cache[name] = (ok, reason)
        return ok, reason

    def _resolve_runner(self, requested: str | None) -> tuple[str, str]:
        """Return (resolved_runner, unavailable_reason)."""
        want = (requested or self.gate_runner or "auto").lower()
        if want == "host":
            return "host", ""
        ok, reason = self._runner_ready("docker")
        if want == "docker":
            return ("docker", "") if ok else ("docker", reason)
        return ("docker", "") if ok else ("host", "")

    def _run_one(self, chk: CheckSpec) -> tuple[int, str, str, str]:
        """Run one command; returns (rc, stdout, combined, runner).

        A launcher failure (OSError/timeout) is retried once: Windows AV scanners
        and transient file locks make an executable fail to start, which is an
        environment fault, not a code defect. A requested-but-unavailable runner
        is reported, never silently downgraded.
        """
        runner, unavailable = self._resolve_runner(chk.runner)
        if unavailable:
            return 127, "", f"RUNNER_UNAVAILABLE: {unavailable}", runner

        if runner == "docker":
            target: list[str] | str = [
                "docker", "run", "--rm", "--network", "none",
                "-v", f"{Path(self.repo_dir).resolve()}:/work", "-w", "/work",
                self.verify_image, "sh", "-lc", chk.command,
            ]
            use_shell = False
        else:
            # `shell=True` on Windows must receive a STRING: a one-element list is
            # quoted as a single argv token and the shell then looks for a file
            # literally named '<python.exe> -m unittest ...'.
            target = chk.command
            use_shell = True

        last_exc: Exception | None = None
        import time as _time
        started = 0.0
        for _attempt in range(2):
            started = _time.perf_counter()
            try:
                proc = subprocess.run(
                    target,
                    cwd=str(self.repo_dir),
                    shell=use_shell,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=self.command_timeout_sec,
                    text=True,
                )
                stdout = proc.stdout or ""
                self._last_elapsed = _time.perf_counter() - started
                return proc.returncode, stdout, (stdout + "\n" + (proc.stderr or "")).strip(), runner
            except (OSError, subprocess.SubprocessError) as exc:
                last_exc = exc
        self._last_elapsed = _time.perf_counter() - started
        return 127, "", f"EXEC_ERROR: {last_exc}", runner

    def _run_batch_docker(
        self, specs: list[CheckSpec], source: str
    ) -> tuple[list[CheckFailure], list[Evidence]]:
        """Run several checks in ONE container (G5).

        Each `docker run` costs ~1.5-2s of startup on this machine, so a gate with
        three checks would pay it three times. Segments are delimited by sentinels
        and each command's own rc is echoed, so per-check attribution is preserved.
        """
        parts: list[str] = []
        for i, chk in enumerate(specs):
            parts.append(
                f'printf "\\n__HARNESS_SEG_{i}\\n"; {chk.command}; '
                f'printf "\\n__HARNESS_RC_{i}=%s\\n" "$?"'
            )
        script = "\n".join(parts)
        cmd = [
            "docker", "run", "--rm", "--network", "none",
            "-v", f"{Path(self.repo_dir).resolve()}:/work", "-w", "/work",
            self.verify_image, "sh", "-lc", script,
        ]
        failures: list[CheckFailure] = []
        evidence: list[Evidence] = []
        import time as _time
        started = _time.perf_counter()
        try:
            proc = subprocess.run(
                cmd, cwd=str(self.repo_dir), shell=False,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                timeout=max(self.command_timeout_sec * max(1, len(specs)), 60),
            )
            raw = (proc.stdout or "") + "\n" + (proc.stderr or "")
        except (OSError, subprocess.SubprocessError) as exc:
            raw = f"EXEC_ERROR: {exc}"

        segments: dict[int, list[str]] = {}
        rcs: dict[int, int] = {}
        current: int | None = None
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped.startswith("__HARNESS_SEG_"):
                try:
                    current = int(stripped.rsplit("_", 1)[1])
                except ValueError:
                    current = None
                segments.setdefault(current if current is not None else -1, [])
                continue
            if stripped.startswith("__HARNESS_RC_"):
                idx, _, value = stripped[len("__HARNESS_RC_"):].partition("=")
                try:
                    rcs[int(idx)] = int(value.strip())
                except ValueError:
                    rcs[int(idx)] = 127
                continue
            segments.setdefault(current if current is not None else -1, []).append(line)

        batch_elapsed = round(_time.perf_counter() - started, 3)
        for i, chk in enumerate(specs):
            body = "\n".join(segments.get(i, [])).strip()
            rc = rcs.get(i, 127)
            tail = "\n".join((body or raw).splitlines()[-25:])
            counted = len([ln for ln in body.splitlines() if ln.strip()])
            evidence.append(
                Evidence(name=chk.name, command=chk.command, exit_code=rc, source=source,
                         tail=tail, counted=counted, stdout_lines=counted, runner="docker",
                         elapsed=batch_elapsed)  # segment-level timing is a follow-up; total first
            )
            if rc != 0 and chk.required:
                failures.append(CheckFailure(name=chk.name, exit_code=rc, tail=tail))
        return failures, evidence

    def _run_checks(self, specs: list[CheckSpec], source: str) -> tuple[list[CheckFailure], list[Evidence]]:
        """Execute checks and keep the machine-checked outcome for every one of them."""
        if len(specs) > 1 and all(self._resolve_runner(c.runner)[0] == "docker"
                                 and not self._resolve_runner(c.runner)[1] for c in specs):
            return self._run_batch_docker(specs, source)
        failures: list[CheckFailure] = []
        evidence: list[Evidence] = []
        for chk in specs:
            rc, stdout, combined, runner = self._run_one(chk)
            tail = "\n".join(combined.splitlines()[-25:])
            counted = len([ln for ln in stdout.splitlines() if ln.strip()])
            evidence.append(
                Evidence(name=chk.name, command=chk.command, exit_code=rc,
                         source=source, tail=tail, counted=counted, stdout_lines=counted,
                         runner=runner, elapsed=round(getattr(self, "_last_elapsed", 0.0), 3))
            )
            if rc != 0 and chk.required:
                failures.append(CheckFailure(name=chk.name, exit_code=rc, tail=tail))
        return failures, evidence

    # -- cross-turn loop ledger -------------------------------------------

    def _ledger_repeat_count(self, fp: str) -> int:
        """How many previous turns already ended with this exact fingerprint."""
        try:
            if not self.ledger_path.exists():
                return 0
            n = 0
            for raw in self.ledger_path.read_text(encoding="utf-8").splitlines():
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if rec.get("fingerprint") == fp and rec.get("verdict") != "green":
                    n += 1
            return n
        except OSError:
            return 0

    def _append_ledger(self, record: dict[str, Any]) -> None:
        try:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with self.ledger_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass  # the ledger must never break the gate

    def evaluate(
        self,
        assistant_text: str,
        mutated_this_turn: bool = True,
        claims: list[dict[str, Any]] | None = None,
        verification_commands: Any = None,
        evidence_policy: str | None = None,
        task_contract: TaskContract | None = None,
    ) -> GateDecision:
        policy = (evidence_policy or self.evidence_policy or "warn").lower()
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
        evidence: list[Evidence] = []
        caller_specs = _normalize_evidence_specs(verification_commands)
        cfg_failures, cfg_evidence = self._run_checks(self.checks, "config")
        caller_failures, caller_evidence = self._run_checks(caller_specs, "caller")
        failures = cfg_failures + caller_failures
        evidence = cfg_evidence + caller_evidence

        residue = scan_residue_files(self.repo_dir, self.residue_globs)

        # Issue #2: quantified/completeness claims must bind to executed checks.
        declared = [str(c.get("text", "")) for c in (claims or []) if isinstance(c, dict)]
        unbound = extract_unbound_claims(assistant_text, declared)
        claim_errors, claim_count_failures, memory_refs = _validate_claims(claims, evidence)
        failures += claim_count_failures

        executed = [e for e in evidence if e.source == "caller"] or evidence
        executed_names = [e.name for e in evidence]
        failed_names = [f.name for f in failures]
        contract = task_contract if task_contract is not None else load_task_contract(self.repo_dir)
        unresolved = unclosed_predicates(contract, executed_names, failed_names) if contract else []
        failure_classes = classify_failures(failures, claim_errors, evidence)
        verifier = verifier_fingerprint(self.repo_dir)

        if failures or residue:
            verdict = "red"
        elif not executed:
            verdict = "no_evidence"
        elif unbound or claim_errors:
            verdict = "unbound_claim"
        elif unresolved:
            verdict = "unclosed_predicate"
        else:
            verdict = "green"

        blocking = verdict == "red" or (verdict != "green" and policy == "enforce")
        warnings: list[str] = []
        verifier_changed = verifier_change_warnings(self.ledger_path, verifier)
        warnings.extend(verifier_changed)
        if verdict != "green" and not blocking:
            warnings.append(
                f"verdict={verdict}: 断言未绑定或本回合无可绑定证据 ({policy} 策略仅告警, "
                f"设为 enforce 可硬拦)"
            )
            if not executed:
                warnings.append(
                    "未执行任何校验: 仓库无 .pi/exit_gate.json 或 checks 为空, 且未传 verification_commands"
                )
            warnings.extend(f"未绑定断言: {s}" for s in unbound[:3])
            warnings.extend(claim_errors[:3])
            warnings.extend(f"未闭合谓词 {u['id']}/{u['check']}: {u['status']}" for u in unresolved[:3])

        if not blocking:
            self.review_retry_count = 0  # any accepted mutated turn clears the review counter
            if verdict == "green":
                self.retry_count = 0
                self.last_fingerprint = ""
            self._append_ledger({"kind": "gate", "verdict": verdict, "fingerprint": "",
                                 "evidence": [e.name for e in evidence], "policy": policy,
                                 "verifier": verifier,
                                 "classes": [c["class"] for c in failure_classes],
                                 "contract": contract.task_id if contract else "",
                                 "runners": [e.runner for e in evidence],
                                 "memory_refs": memory_refs,
                                 "elapsed": [e.elapsed for e in evidence]})
            return GateDecision(
                passed=True,
                action="pass",
                verdict=verdict,
                evidence=evidence,
                unbound_claims=unbound,
                claim_errors=claim_errors,
                failure_classes=failure_classes,
                unclosed_predicates=unresolved,
                verifier_hash=verifier,
                verifier_changed=verifier_changed,
                memory_refs=memory_refs,
                warnings=warnings,
            )

        fp = _fingerprint(failures, residue) if (failures or residue) else (
            f"{verdict}:" + ",".join((unbound[:1] + claim_errors[:1]))[:80]
        )
        repeated = fp == self.last_fingerprint
        self.last_fingerprint = fp
        prior = self._ledger_repeat_count(fp)
        escalate_root_cause = prior >= 2

        # State-coupled: only flag shirking when the repo is actually red or dirty!
        shirking_hits = detect_shirking(assistant_text)

        self._append_ledger({"kind": "gate", "verdict": verdict, "fingerprint": fp, "policy": policy,
                             "residue": residue[:5], "failures": [f.name for f in failures],
                             "verifier": verifier,
                             "classes": [c["class"] for c in failure_classes],
                             "contract": contract.task_id if contract else "",
                             "runners": [e.runner for e in evidence],
                             "memory_refs": memory_refs,
                             "elapsed": [e.elapsed for e in evidence]})

        if self.retry_count >= self.max_gate_retries:
            return GateDecision(
                passed=False,
                action="halt_to_user",
                failures=failures,
                residue_files=residue,
                shirking_hits=shirking_hits,
                verdict=verdict,
                evidence=evidence,
                unbound_claims=unbound,
                claim_errors=claim_errors,
                failure_classes=failure_classes,
                unclosed_predicates=unresolved,
                verifier_hash=verifier,
                verifier_changed=verifier_changed,
                memory_refs=memory_refs,
                warnings=warnings,
                loop_repeat_count=prior + 1,
                escalate_root_cause=True,
                fingerprint=fp,
                retry_count=self.retry_count,
            )

        self.retry_count += 1
        action = "escalate_and_bounce" if (repeated or escalate_root_cause) else "bounce"
        lines = [
            f"[HARNESS_EXIT_GATE_RETRY] Attempt {self.retry_count}/{self.max_gate_retries} "
            f"(fingerprint={fp}, verdict={verdict})."
        ]
        if shirking_hits:
            lines.append(
                f"[ANTI_SHIRKING_INTERCEPT] Detected buck-passing phrasing ({', '.join(shirking_hits)}) "
                f"while verification is red. Fix blocking failures instead of dismissing them."
            )
        if repeated:
            lines.append("[ESCALATE_REASONING: high] Identical error repeated; re-analyze root cause.")
        if escalate_root_cause:
            lines.append(
                f"[LOOP_LEDGER] This fingerprint already appeared {prior} time(s) in earlier turns "
                f"({self.ledger_path.name}). Do not repeat the same fix: state a root-cause hypothesis, "
                f"keep at most 2 candidate directions, then run one discriminating check or report the "
                f"blocking unknown to the user."
            )
        if verdict == "no_evidence":
            lines.append(
                "[NO_EVIDENCE] Nothing was executed, so no completion claim is justified. Add checks to "
                ".pi/exit_gate.json, or pass verification_commands so the gate runs them itself."
            )
        for snippet in unbound[:5]:
            lines.append(f"Unbound quantified claim (no executed check backs it): {snippet}")
        for err in claim_errors[:5]:
            lines.append(f"Claim binding error: {err}")
        for cls in failure_classes:
            lines.append(f"Failure class [{cls['class']}] {cls['name']} -> {cls['action']}")
        for pred in unresolved[:5]:
            lines.append(
                f"Unclosed predicate {pred['id']} (check={pred['check']}, {pred['status']}): {pred['statement']}"
            )
        for warn in verifier_changed:
            lines.append(f"[VERIFIER_CHANGED] {warn}")
        for f in failures:
            lines.append(f"Failed check `{f.name}` (exit={f.exit_code}):\n{f.tail}")
        if residue:
            lines.append("Leftover residue files to remove: " + ", ".join(residue))
        if unbound or claim_errors:
            lines.append(
                "Bind each quantified/completeness claim to an executed check via "
                "run_gate(claims=[{text, check}]), or qualify it explicitly (e.g. '抽样 5/22 页，其余未验证')."
            )

        return GateDecision(
            passed=False,
            action=action,
            failures=failures,
            residue_files=residue,
            shirking_hits=shirking_hits,
            verdict=verdict,
            evidence=evidence,
            unbound_claims=unbound,
            claim_errors=claim_errors,
            failure_classes=failure_classes,
            unclosed_predicates=unresolved,
            verifier_hash=verifier,
            verifier_changed=verifier_changed,
            memory_refs=memory_refs,
            warnings=warnings,
            loop_repeat_count=prior + 1,
            escalate_root_cause=escalate_root_cause,
            fingerprint=fp,
            retry_count=self.retry_count,
            bounce_prompt="\n".join(lines),
        )
