"""Data-driven task routing (oh-my-openagent-inspired, hardcode removed).

OmO picks per-category models/efforts from TypeScript constants; editing means a
code change. Here the same (category -> profile/effort/budget/model) mapping
lives in config/task_routing.yaml: reviewable, diffable, and validated against
the capability matrix by scripts/capability_matrix.py --validate-routing.

The router is advisory: it never overrides an explicit profile/effort given by
the caller, and the gateway still owns the final (model, effort) decision —
`effort` here is a hint that degrades gracefully via max_effort clamping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "config" / "task_routing.yaml"
VALID_PROFILES = ("explorer", "coder", "deep", "critic")
VALID_EFFORTS = ("minimal", "low", "medium", "high")
PROFILE_TO_TIER = {"explorer": "system_1", "coder": "system_1_5", "deep": "system_2", "critic": "system_2_plus"}

_cache: dict[str, dict[str, Any]] = {}


@dataclass
class RouteDecision:
    category: str
    profile: str
    effort: str
    budget: int
    model: str | None = None
    exclude_drafter: bool = False
    source: str = "table"  # table | default | explicit
    note: str = ""
    warnings: list[str] = field(default_factory=list)


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    path = Path(config_path or DEFAULT_CONFIG)
    key = str(path.resolve())
    if key in _cache:
        return _cache[key]
    if not path.exists():
        _cache[key] = {}
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    _cache[key] = data
    return data


def classify_category(task_text: str, config: dict[str, Any] | None = None) -> tuple[str, str | None]:
    """Return (category, matched_keyword).

    Categories carry an explicit `priority` (default 0); higher priority wins
    regardless of file order, so precedence is data, not YAML ordering. Within
    one priority, first category with a keyword hit wins. (First file-order-hit
    alone was reviewed as FAIL by a critic sub-agent: order-dependent precedence
    is implicit hardcoding.)
    """
    cfg = config if config is not None else load_config()
    low = (task_text or "").lower()
    entries = list((cfg.get("categories") or {}).items())
    entries.sort(key=lambda kv: -int((kv[1] or {}).get("priority", 0)))
    for name, entry in entries:
        for kw in entry.get("match") or []:
            if kw.lower() in low:
                return name, kw
    return "default", None


def route_task(
    task_text: str,
    config: dict[str, Any] | None = None,
    capability: dict[str, Any] | None = None,
    explicit_profile: str | None = None,
    explicit_effort: str | None = None,
) -> RouteDecision:
    """Resolve (category) -> dispatch decision, with graceful degradation.

    `capability` is the output of scripts/capability_matrix.build_matrix()
    (models keyed by name with efforts_allowed / max_effort). When provided,
    over-declared efforts are clamped and unknown model pins are warned about —
    never silently dropped.
    """
    cfg = config if config is not None else load_config()
    category, kw = classify_category(task_text, cfg)
    entry = (cfg.get("categories") or {}).get(category) or cfg.get("default") or {}
    decision = dict(entry.get("decision") or {})

    profile = explicit_profile or str(decision.get("profile") or "coder")
    effort = explicit_effort or str(decision.get("effort") or "medium")
    budget = int(decision.get("budget") or 4096)
    model = decision.get("model") or None
    exclude = bool(decision.get("exclude_drafter", False))
    source = "table" if (explicit_profile is None and category != "default") else (
        "explicit" if explicit_profile else "default")

    warnings: list[str] = []
    if profile not in VALID_PROFILES:
        warnings.append(f"未知 profile '{profile}', 回落 coder")
        profile = "coder"
    if effort not in VALID_EFFORTS:
        warnings.append(f"未知 effort '{effort}', 回落 medium")
        effort = "medium"

    if capability and model:
        rows = {r["model"]: r for r in capability.get("models") or []}
        row = rows.get(model)
        if row is None:
            warnings.append(f"路由表钉住的模型 '{model}' 不在 quota_policy 中, 视为未钉住")
            model = None
        elif effort in (row.get("efforts_clamped") or []):
            warnings.append(f"effort '{effort}' 超过 {model} 的 max_effort, 网关会钳制")

    return RouteDecision(
        category=category, profile=profile, effort=effort, budget=budget,
        model=model, exclude_drafter=exclude, source=source,
        note=str(entry.get("note") or ""), warnings=warnings,
    )


def validate_against_capability(
    config: dict[str, Any], capability: dict[str, Any]
) -> list[str]:
    """Every routing entry must be servable: valid profile/effort, model exists,
    effort not hard-clamped. Returns violation strings (empty = ok).

    Keyword overlap across categories is reported as a WARNING line (overlaps
    can be intentional when priorities disambiguate) — violations and warnings
    share the list, prefixed, so --validate-routing can stay strict while the
    human sees both.
    """
    rows = {r["model"]: r for r in capability.get("models") or []}
    violations: list[str] = []
    entries = dict(config.get("categories") or {})
    entries["<default>"] = config.get("default") or {}

    seen: dict[str, str] = {}
    for name, entry in (config.get("categories") or {}).items():
        for kw in entry.get("match") or []:
            key = kw.lower()
            if key in seen and seen[key] != name:
                violations.append(
                    f"warning: 关键词 '{kw}' 同时出现在 {seen[key]} 与 {name}; "
                    f"由 priority 决断, 确认这是有意的"
                )
            seen.setdefault(key, name)

    for name, entry in entries.items():
        d = entry.get("decision") or {}
        profile, effort = d.get("profile"), d.get("effort")
        if profile not in VALID_PROFILES:
            violations.append(f"{name}: 未知 profile '{profile}'")
        if effort not in VALID_EFFORTS:
            violations.append(f"{name}: 未知 effort '{effort}'")
        model = d.get("model")
        if model:
            row = rows.get(model)
            if row is None:
                violations.append(f"{name}: 模型 '{model}' 不在 quota_policy 中")
            elif effort in (row.get("efforts_clamped") or []):
                violations.append(f"{name}: effort '{effort}' 被 {model} 的 max_effort 钳制, 请改路由表")
    return violations


def as_dict(route: RouteDecision) -> dict[str, Any]:
    return {
        "category": route.category,
        "profile": route.profile,
        "tier": PROFILE_TO_TIER.get(route.profile, "system_1_5"),
        "effort": route.effort,
        "budget": route.budget,
        "model": route.model,
        "exclude_drafter": route.exclude_drafter,
        "source": route.source,
        "note": route.note,
        "warnings": route.warnings,
    }
