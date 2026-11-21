"""Output-Contract Tier-Tag Validator & Injector (response-boundary enforcement).

The harness output contract (SKILL.md / AGENTS.md §3) requires every
user-facing answer to begin with a `[Tier: ... | Mode: ...]` tag. Compliant
models already emit it; this guard hard-enforces the contract at the gateway
boundary: when the upstream response omits the tag, the canonical tag derived
from the routing decision is injected. Compliant responses pass through
untouched. Injection events are traced for auditability.

This module also hosts the review-turn contract checks (issue #1):
  * `check_output_structure`   — three-section anchors, silent-promotion
    detection (header Confidence Cap vs. weakest `[Lx]` body label),
    and the L3 scope/counter-example proximity rule.
  * `check_remediation_completeness` — a declared defect must ship a complete
    fix plan (acceptance criteria + rollback path); downgrading a declared
    defect to "write a doc / known issues / defer" is intercepted unless an
    explicit L4 trade-off is cited in the reply.
Both are pure, deterministic and mirrored by `orchestrator/exit_gate.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

TIER_LABELS: dict[str, str] = {
    "system_0": "Reflexive Execution (Tier 0)",
    "system_1": "Fast Intuition (Tier 1)",
    "system_1_5": "Structured Analysis (Tier 1.5)",
    "system_2": "Deliberative Derivation (Tier 2)",
    "system_2_plus": "Metacognitive Critic (Tier 2+)",
}

CONVERGE_PATTERNS = re.compile(r"(收敛|converge|审计|audit|结论|拍板|复核|critic)", re.I)
EXPLORE_PATTERNS = re.compile(r"(探索|发散|头脑风暴|brainstorm|explore|初筛|点子)", re.I)

LEADING_TAG_RE = re.compile(r"^\s*\[Tier:[^\]\n]*\]")

# ---------------------------------------------------------------------------
# Review-turn contract checks (issue #1: remediation completeness + structure)
# ---------------------------------------------------------------------------

STRUCTURED_TIERS = {"system_1_5", "system_2", "system_2_plus"}

# Anti-false-positive guard: short acknowledgements ("ok", "答案是 42") carry no
# deliverable structure to validate; the three-section requirement targets
# substantial review/analysis outputs only.
MIN_STRUCTURED_LEN = 100

# Section anchors for the mandatory three-part structure (zh + en synonyms).
SECTION_CORE_RE = re.compile(r"(核心结论|core conclusion)", re.I)
SECTION_BREAKDOWN_RE = re.compile(r"(认识论分解|epistemic breakdown|依据分层)", re.I)
SECTION_GAPS_RE = re.compile(r"(证据缺口|evidence gap)", re.I)

HEADER_CAP_RE = re.compile(r"Confidence Cap:\s*(L[1-5])", re.I)
BODY_LAYER_RE = re.compile(r"\[L([1-5])\b")
L3_TAG_RE = re.compile(r"\[L3\b")
L3_SCOPE_RE = re.compile(r"(适用|scope|适用范围)", re.I)
L3_COUNTER_RE = re.compile(r"(反例|counter[- ]?example|失效)", re.I)

# Declared-defect item anchors. Deliberately specific (requires an item
# number) so the compliant "证据缺口 & Complete Remediation Plan" section
# header alone never triggers the check.
DEFECT_ITEM_RE = re.compile(
    r"(?:\bP[1-9]\d?\b|缺陷\s*#?[1-9]\d?|缺口\s*#?[1-9]\d?|问题\s*#?[1-9]\d?|"
    r"\bdefect\s*#?[1-9]\d?|\bissue\s*#?[1-9]\d?)",
    re.I,
)
ACCEPTANCE_RE = re.compile(r"(验收|acceptance)", re.I)
ROLLBACK_RE = re.compile(r"(回退|回滚|rollback|恢复路径)", re.I)
DOWNGRADE_RE = re.compile(
    r"(最小后续动作|minimal next (?:actions|steps)|补一段文档|补充文档|写进已知问题|"
    r"记为已知问题|记入已知问题|留待观察|defer(?:red)? to)",
    re.I,
)
# Explicit user L4 trade-off cited inside the reply (review-only requests).
L4_TRADEOFF_RE = re.compile(
    r"(本次只出评审结论|只要评审结论|只出评审结论|只列\s*file:line|只记录\s*file:line|"
    r"不需要修复方案|暂不修复|review[- ]only|no fix (?:needed|required))",
    re.I,
)


def detect_mode(user_text: str, tier: str) -> str:
    """Infer Explore/Converge mode from the last user message (keyword heuristic, L3)."""
    if CONVERGE_PATTERNS.search(user_text or ""):
        return "Converge"
    if EXPLORE_PATTERNS.search(user_text or ""):
        return "Explore"
    # Default: only the deliberative tiers converge; routine analysis stays exploratory.
    return "Converge" if tier in ("system_2", "system_2_plus") else "Explore"


def build_tier_tag(tier: str, mode: str) -> str:
    label = TIER_LABELS.get(tier, tier)
    return f"[Tier: {label} | Mode: {mode}]"


def ensure_text_tag(text: str, tag: str) -> tuple[str, bool]:
    """Return (text, injected). Inject `tag` when the text lacks a leading tier tag."""
    if not text or not text.strip():
        return text, False
    if LEADING_TAG_RE.match(text):
        return text, False
    return f"{tag}\n\n{text.lstrip()}", True


def guard_openai_message(data: dict, tag: str) -> bool:
    """Ensure the first assistant message in a non-streaming OpenAI response starts with the tag."""
    try:
        msg = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return False
    if msg.get("tool_calls") and not (msg.get("content") or "").strip():
        return False  # pure tool-call turn: no user-facing text, do not inject
    content = msg.get("content")
    if not isinstance(content, str):
        return False
    new_text, injected = ensure_text_tag(content, tag)
    if injected:
        msg["content"] = new_text
    return injected


def guard_openai_stream_delta(delta: dict, tag: str) -> bool:
    """Prepend the tag to the first non-empty content delta of an OpenAI SSE stream."""
    content = delta.get("content")
    if not isinstance(content, str) or not content:
        return False
    new_text, injected = ensure_text_tag(content, tag)
    if injected:
        delta["content"] = new_text
    return injected


def guard_anthropic_content(data: dict, tag: str) -> bool:
    """Ensure the first text block in a non-streaming Anthropic response starts with the tag."""
    content = data.get("content")
    if not isinstance(content, list) or not content:
        return False
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str) and block["text"].strip():
            new_text, injected = ensure_text_tag(block["text"], tag)
            if injected:
                block["text"] = new_text
            return injected
    # Pure tool_use turns carry no user-facing text: leave them untouched.
    return False


def guard_anthropic_stream_delta(delta: dict, tag: str) -> bool:
    """Prepend the tag to the first non-empty text_delta of an Anthropic SSE stream."""
    if delta.get("type") != "text_delta":
        return False
    text = delta.get("text")
    if not isinstance(text, str) or not text:
        return False
    new_text, injected = ensure_text_tag(text, tag)
    if injected:
        delta["text"] = new_text
    return injected


@dataclass
class StreamTagGuard:
    """Stateful SSE prefix buffer preventing split-chunk duplicate `[Tier: ...]` tags.

    Upstream may split the tag across chunks ("[" + "Tier: ...]"); a stateless
    per-chunk check then injects a second copy. This buffer decides exactly once.
    """

    tag: str
    max_probe_chars: int = 24
    _buf: str = ""
    _decided: bool = False
    injected: bool = False

    def feed(self, chunk: str) -> str | None:
        """Feed a content delta; returns text to emit, or None while still probing the prefix."""
        if self._decided:
            return chunk
        if not chunk:
            return None
        self._buf += chunk
        stripped = self._buf.lstrip()
        if not stripped:
            return None
        if not stripped.startswith("["):
            # No leading tag marker: inject the canonical tag and flush the buffer once.
            self._decided = True
            self.injected = True
            out = self.tag + "\n\n" + stripped
            self._buf = ""
            return out
        if ("\n" in stripped) or ("]" in stripped) or len(stripped) >= self.max_probe_chars:
            self._decided = True
            out, self.injected = ensure_text_tag(self._buf, self.tag)
            self._buf = ""
            return out
        return None

    def flush(self) -> str | None:
        """Emit any buffered prefix if the stream ended before a decision was made."""
        if self._decided or not self._buf:
            return None
        self._decided = True
        out, self.injected = ensure_text_tag(self._buf, self.tag)
        self._buf = ""
        return out


def _header_cap(text: str) -> int | None:
    m = HEADER_CAP_RE.search(text or "")
    return int(m.group(1)[1]) if m else None


def weakest_body_layer(text: str) -> int | None:
    """Weakest (highest-numbered) `[Lx]` epistemic label present in the body."""
    layers = [int(n) for n in BODY_LAYER_RE.findall(text or "")]
    return max(layers) if layers else None


def check_output_structure(text: str, tier: str, mode: str) -> list[str]:
    """Three-part structure, silent-promotion and L3 scope/counter-example checks.

    Applies only to substantial structured outputs (Tier >= 1.5 or Converge
    mode, and at least MIN_STRUCTURED_LEN characters). Returns a list of
    human-readable violation strings; empty means compliant.
    """
    if not text or not text.strip():
        return []
    if len(text.strip()) < MIN_STRUCTURED_LEN:
        return []  # short acknowledgement: no deliverable structure to validate
    if tier not in STRUCTURED_TIERS and mode != "Converge":
        return []  # Tier 0/1 and non-converged turns carry no structure requirement

    violations: list[str] = []
    missing = []
    if not SECTION_CORE_RE.search(text):
        missing.append("Core Conclusion/核心结论")
    if not SECTION_BREAKDOWN_RE.search(text):
        missing.append("Epistemic Breakdown/认识论分解")
    if not SECTION_GAPS_RE.search(text):
        missing.append("Evidence Gaps/证据缺口")
    if missing:
        violations.append("缺少三段式锚点: " + ", ".join(missing))

    # Silent promotion: a declared header cap weaker than the body's weakest
    # layer is only allowed; a stronger header over L3-derived body labels is not.
    cap = _header_cap(text)
    body = weakest_body_layer(text)
    if cap is not None and body is not None and cap < body:
        violations.append(
            f"silent promotion: 头部 Confidence Cap L{cap} 弱于正文最弱依据 L{body} "
            f"(代码推演/经验判断封顶 L{body})"
        )

    # L3 proximity rule: within 3 lines after each `[L3` label there must be a
    # scope anchor AND a counter-example anchor.
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        for m in L3_TAG_RE.finditer(line):
            window = "\n".join(lines[idx:idx + 3])
            has_scope = bool(L3_SCOPE_RE.search(window))
            has_counter = bool(L3_COUNTER_RE.search(window))
            if not (has_scope and has_counter):
                missing_bits = []
                if not has_scope:
                    missing_bits.append("适用/scope")
                if not has_counter:
                    missing_bits.append("反例/counter-example")
                violations.append(
                    f"[L3] 标签(第{idx + 1}行)后 3 行内缺少: {', '.join(missing_bits)}"
                )
    return violations


def _defect_items(text: str) -> list[tuple[str, str]]:
    """Split text into (item_label, segment) declared-defect sections."""
    matches = list(DEFECT_ITEM_RE.finditer(text))
    items: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        items.append((m.group(0), text[m.start():end]))
    return items


def check_remediation_completeness(text: str) -> list[str]:
    """Declared defects must ship a complete fix plan (issue #1).

    * No declared-defect anchors -> not a review-of-defects turn: pass.
    * Explicit L4 trade-off cited in the reply (review-only request) -> pass.
    * Each numbered defect item needs an acceptance anchor and a rollback
      anchor inside its own segment.
    * Downgrade phrasing co-occurring with declared defects -> violation.
    """
    if not text or not text.strip():
        return []
    items = _defect_items(text)
    if not items:
        return []
    if L4_TRADEOFF_RE.search(text):
        return []  # user explicitly scoped this turn to review-only (L4)

    violations: list[str] = []
    for label, segment in items:
        if not ACCEPTANCE_RE.search(segment):
            violations.append(f"{label}: 已声明缺陷但缺少验收判据 (验收/acceptance)")
        if not ROLLBACK_RE.search(segment):
            violations.append(f"{label}: 已声明缺陷但缺少回退路径 (回退/rollback)")
    downgrade = DOWNGRADE_RE.search(text)
    if downgrade:
        violations.append(
            f"缺陷降级: '{downgrade.group(0)}' 与已声明缺陷同现; "
            f"缺陷必须给出完整修复方案(改动点/迁移影响/回退/验收), "
            f"除非显式引用 L4 运营决策依据"
        )
    return violations


def build_contract_intercept(violations: list[str], *, retry: bool) -> str:
    """Deterministic intercept prompt appended to bounced responses."""
    lines = [
        "[OUTPUT_CONTRACT_INTERCEPT] 输出契约违规(评审回合):",
        *[f"  - {v}" for v in violations],
    ]
    if retry:
        lines.append(
            "请按契约重做本回合: 三段式结构 (Core Conclusion / Epistemic Breakdown / "
            "Evidence Gaps), Confidence Cap 不得高于正文最弱依据层, 每个 [L3] 附适用"
            "范围与反例, 已声明缺陷必须给出完整修复方案 (改动点/迁移影响/回退路径/可证伪验收判据)。"
        )
    else:
        lines.append(
            "[ESCALATE_TO_L2] 重试后仍违规, 按 L2 上报人工复核, 不得再次自动打回。"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Underdetermination guard (issue #3): a raised decision point must be open
# ---------------------------------------------------------------------------

DECISION_ASK_RE = re.compile(
    r"(需要你(?:来)?(?:决定|拍板|裁量|定夺|选)|请你(?:决定|拍板|裁量|确认)|需要(?:你)?确认|"
    r"待你决策|由你决定|决策点|需要裁量|decision needed|need your (?:decision|call))",
    re.I,
)
L4_ANCHOR_RE = re.compile(
    r"(\bL4\b|预算|工期|人力|团队|风险取舍|产品取舍|商业取舍|合规要求|"
    r"budget|headcount|timeline|risk trade|product trade)",
    re.I,
)
L2_GAP_ANCHOR_RE = re.compile(
    r"(缺(?:少|失)?(?:L2|证据|数据|日志|凭据|文档)|没有(?:可核查|可验证|一手)|"
    r"L2\s*缺失|未检索|需外部检索|evidence gap)",
    re.I,
)

# ---------------------------------------------------------------------------
# Research discipline: SOTA/superlative claims need an external source anchor
# ---------------------------------------------------------------------------

SOTA_CLAIM_RE = re.compile(
    r"(\bSOTA\b|state[- ]of[- ]the[- ]art|最佳方案|最优方案|最流行|主流方案|业界标准|"
    r"公认做法|普遍做法|best[- ]in[- ]class|de[- ]facto standard)",
    re.I,
)
SOURCE_ANCHOR_RE = re.compile(
    r"(https?://|arxiv[:\s]|doi[:\s]|github\.com/|huggingface\.co/|"
    r"检索于|accessed\s+\d{4}|\b(?:19|20)\d{2}-\d{2}-\d{2}\b|RFC\s?\d+)",
    re.I,
)
NOT_SEARCHED_RE = re.compile(
    r"(未检索|未做外部检索|凭记忆|from memory|without (?:an )?external search|no external search)",
    re.I,
)
FENCE_RE = re.compile(r"```.*?```", re.S)


def strip_noise(text: str) -> list[str]:
    """Drop fenced code and blockquoted lines so quoted material cannot trip checks."""
    body = FENCE_RE.sub("\n", text or "")
    return [ln for ln in body.splitlines() if not ln.lstrip().startswith(">")]


def check_underdetermination(text: str) -> list[str]:
    """A raised decision point must be genuinely underdetermined (issue #3).

    Every ask anchor ("需要你拍板" / "请确认" / "决策点") needs, within the next
    3 lines, an L4 trade-off anchor (budget/risk/team/product) or a missing-L2
    anchor. Otherwise the model is asking about something already closed by
    definition or by evidence.
    """
    lines = strip_noise(text)
    violations: list[str] = []
    for idx, line in enumerate(lines):
        for m in DECISION_ASK_RE.finditer(line):
            window = "\n".join(lines[idx:idx + 3])
            if L4_ANCHOR_RE.search(window) or L2_GAP_ANCHOR_RE.search(window):
                continue
            violations.append(
                f"伪决策点(第{idx + 1}行) '{m.group(0)}': 未标明触发层; "
                f"若不问时答案唯一则直接给结论, 确需裁量请注明 L4 取舍或缺失的 L2 证据"
            )
    return violations


def check_external_grounding(text: str) -> list[str]:
    """SOTA/superlative claims need a source anchor or a no-search declaration."""
    body = "\n".join(strip_noise(text))
    m = SOTA_CLAIM_RE.search(body)
    if not m:
        return []
    if SOURCE_ANCHOR_RE.search(body) or NOT_SEARCHED_RE.search(body):
        return []
    return [
        f"选型/最优性断言 '{m.group(0)}' 缺少来源锚点(URL/arXiv/DOI/检索日期); "
        f"若本回合未做外部检索, 请显式写明并据实下调置信上限"
    ]


def check_response_contract(text: str, tier: str, mode: str) -> list[str]:
    """Run structure + remediation checks; returns the union of violations."""
    return (
        check_output_structure(text, tier, mode)
        + check_remediation_completeness(text)
        + check_underdetermination(text)
        + check_external_grounding(text)
    )
