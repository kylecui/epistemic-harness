#!/usr/bin/env python3
"""Controlled A/B Style & Epistemic Regression Runner (TC-07..TC-09).

Compares Control (no AGENTS.md / Chinese-only baseline) vs. Treatment (English
AGENTS.md with English-reasoning + anti-jargon Chinese rewrite slice) across:
  1. Epistemic assertions (L1/L2/L3 separation, stop-loss, conflict honesty)
  2. Chinese internet/corporate buzzword leakage (zero-tolerance list)
  3. Stiff translationese patterns
  4. English reasoning corporate slop (when thought traces are available)
  5. Prose density (average Chinese sentence length)

Usage:
  # Score captured baseline vs. treatment transcripts locally:
  python3 run_style_ab_eval.py --replay

  # Run live A/B against Pi CLI (requires `pi` on PATH):
  python3 run_style_ab_eval.py --live --pi-bin pi
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

import yaml

DEFAULT_YAML = Path(__file__).resolve().parent / "golden_cases_style_ab.yaml"


@dataclass
class CaseScore:
    case_id: str
    arm: str
    epistemic_pass: bool
    zh_buzzwords: list[str]
    translationese_hits: list[str]
    en_slop_hits: list[str]
    thought_lang: str
    char_count: int
    avg_sentence_chars: float
    failures: list[str]

    @property
    def passed(self) -> bool:
        return (
            self.epistemic_pass
            and not self.zh_buzzwords
            and not self.translationese_hits
            and not self.en_slop_hits
            and not self.failures
        )


def detect_thought_lang(thoughts: str) -> str:
    if not thoughts.strip():
        return "N/A"
    zh_chars = len(re.findall(r"[\u4e00-\u9fff]", thoughts))
    en_words = len(re.findall(r"[A-Za-z]{2,}", thoughts))
    if zh_chars > en_words * 2:
        return "ZH"
    if en_words > zh_chars * 2:
        return "EN"
    return "MIXED"


def avg_sentence_length(text: str) -> float:
    cleaned = re.sub(r"`[^`]+`", "", text)
    cleaned = re.sub(r"\[[^\]]+\]", "", cleaned)
    sentences = [s.strip() for s in re.split(r"[。！？\n]+", cleaned) if len(s.strip()) >= 4]
    if not sentences:
        return 0.0
    return round(sum(len(s) for s in sentences) / len(sentences), 1)


def score_response(
    case: dict[str, Any],
    style_rules: dict[str, Any],
    arm: str,
    reply: str,
    thoughts: str = "",
) -> CaseScore:
    assertions = case.get("assertions", {})
    failures: list[str] = []

    must_any = assertions.get("must_contain_any", [])
    if must_any and not any(tok in reply for tok in must_any):
        failures.append(f"missing_any:{must_any}")

    for forbidden in assertions.get("must_not_contain", []):
        if forbidden in reply:
            failures.append(f"forbidden_phrase:{forbidden}")

    epistemic_pass = len(failures) == 0

    zh_buzzwords: list[str] = []
    translationese_hits: list[str] = []
    en_slop_hits: list[str] = []

    if assertions.get("check_style_rules", True):
        for bw in style_rules.get("forbid_zh_buzzwords", []):
            if bw in reply:
                zh_buzzwords.append(bw)
        for pat in style_rules.get("forbid_translationese_regex", []):
            if re.search(pat, reply):
                translationese_hits.append(pat)
        if thoughts:
            for slop in style_rules.get("forbid_en_slop", []):
                if re.search(rf"\b{re.escape(slop)}\b", thoughts, re.IGNORECASE):
                    en_slop_hits.append(slop)

    return CaseScore(
        case_id=case["id"],
        arm=arm,
        epistemic_pass=epistemic_pass,
        zh_buzzwords=zh_buzzwords,
        translationese_hits=translationese_hits,
        en_slop_hits=en_slop_hits,
        thought_lang=detect_thought_lang(thoughts),
        char_count=len(reply),
        avg_sentence_chars=avg_sentence_length(reply),
        failures=failures,
    )


# Captured transcripts from the live isolated subagent A/B run (2026-11-20)
REPLAY_TRANSCRIPTS: dict[str, dict[str, dict[str, str]]] = {
    "control_zh_skill": {
        "TC-07": {
            "thoughts": "解析你的业务与技术咨询问题 分析你的认知框架规则 评估你的电商业务订单表整合方案 评估你的业务架构盲区",
            "reply": (
                "[档位: 结构分析档 | 状态: 收敛态 | 结论上限: L3]\n"
                "核心结论：受限于 L3 架构经验与关键业务数据缺口，建议暂缓“全面业务中台化”立项，先用 2 周量化跨线复用价值，再决定整合范围。\n"
                "- [L2/L4 事实与约束]：公司规模 80 人，现有 3 条业务线且订单表独立。\n"
                "- [L3 经验与边界]：顾问所称“大厂中台降本增效”仅为待验证假设。其适用前提是跨线流程高度趋同且研发人力充裕；反例是中小团队在业务差异大时强推大中台，反而因过度抽象推高维护成本、拖慢一线迭代。\n"
                "- 最小未知变量：3 条线的库存/会员重叠率及跨线重复研发工时（决定采用“轻量数据汇总”还是“局部打通会员库存”）。"
            ),
        },
        "TC-08": {
            "thoughts": "评估你的 B2B 留存率下滑成因",
            "reply": (
                "[档位: 结构分析档 | 状态: 收敛态 | 结论上限: L3]\n"
                "核心结论：因缺乏流失归因的一手证据，不建议立刻扩招 5 名 CSM 或开发会员积分体系；下季度前 3 周应先止损排因，再定人力与产品投入。\n"
                "- [L2 事实]：90 天留存率从 78% 降至 64%（降幅 14 个百分点）。\n"
                "- [L3 经验与边界]：销售团队的归因属未验证假设。CSM 体系适用于高客单、重交付的 B2B 场景，若实为产品缺陷或价值不足则扩招无效；会员积分偏 C 端高频激励，在 B2B 续费决策中常失效。\n"
                "- 建议动作：① 访谈 10–15 家近期流失客户；② 按客群与使用深度拆解留存及工单数据；③ 凭实证决定小规模试点 CSM 或优先修产品。"
            ),
        },
        "TC-09": {
            "thoughts": "剖析你关于企业级AI安全治理与全员落地的两难执行方案 评估你的硬性合规前提冲突 正在依据你的管理取舍起草分级落地方案",
            "reply": (
                "[档位: 深度推演档 | 状态: 收敛态 | 结论上限: L1]\n"
                "核心结论：该目标存在底层前提冲突，无法直接出具同时满足两项要求的执行方案，需先请管理层明确效率与安全的取舍边界。\n"
                "- [L1 客观边界]：依据信息安全与数据流转的客观规律，“各部门自由接入外部大模型”与“100% 零数据泄露”在逻辑和技术上互斥。\n"
                "- 建议动作：① 向老板书面呈报上述互斥点并确认优先级；② 划定严禁出境/出网的核心数据红线；③ 待取舍明确后再拆解 2 个月分阶段落地计划。"
            ),
        },
    },
    "treatment_en_agents_md": {
        "TC-07": {
            "thoughts": "Analyzing your runtime contract Evaluating your runtime contract for test cases Translating your executive responses into professional Chinese",
            "reply": (
                "[Tier: Deep | Mode: Explore | Confidence Cap: L3]\n"
                "结论：暂缓立项，不建议现在建统一业务中台。\n"
                "顾问把“统一中台”当成通用法则，这其实只是经验判断（L3）。它只在业务线众多、流量巨大、且有专职平台团队的大型公司成立。反例很常见：不到百人的团队过早合并订单和库存表，三条业务线会互相拖慢发版，维护公共系统的成本反而超过重复开发的开销，甚至大厂近年也在拆解过重的中台。\n"
                "从工程规律看（L1），系统合并必然带来耦合与协调成本。目前我们缺少核心事实（L2）：三条线到底有多少共用商品、重复会员和重复开发工时？\n"
                "给管理层的建议：1. 否决全面重构方案，避免研发停滞。2. 用两周盘点三套表的真实重叠度与人力损耗（补齐 L2）。3. 若重叠度低，保持分库分表，只做只读报表汇总即可；仅在跨线共享业务确实成为瓶颈时，再按需拆分公共服务。"
            ),
        },
        "TC-08": {
            "thoughts": "Refining your architectural audit tiers for your B2B retention strategy Structuring your retention audit into a phased quarterly plan Scrutinizing your retention metrics to separate root causes from symptoms",
            "reply": (
                "[Tier: Deep | Mode: Explore | Confidence Cap: L3]\n"
                "评估结论：暂停招 5 名 CSM，取消会员积分方案。\n"
                "目前唯一确凿的事实（L2）是 90 天留存从 78% 跌到 64%，但流失根因完全未知。销售团队的建议只是经验猜测（L3）：配 CSM 只在产品过关、客户不会用时有效；积分体系只适合高频复购的消费品。反例很明显：B2B 企业续费看投入产出比，积分留不住客户；若流失源于产品缺陷、交付跳票或销售过度承诺，盲目扩招 5 人只会推高固定成本，根本止不住掉血（L1）。\n"
                "下季度行动计划：1. 前 3 周（查清 L2 根因）：按客户规模、行业、签约渠道和核心功能使用率拆解流失数据，深度访谈 15–20 家流失客户，归类真实原因。2. 第 4–12 周（对症投入）：若是产品或实施问题，优先修缺陷、改上线流程；只有证实问题出在客户使用不足时，才先招 1–2 名 CSM 试点大客户，再决定是否扩编。"
            ),
        },
        "TC-09": {
            "thoughts": "Spotlighting your conflicting goals to halt your unsafe rollout plan Scrubbing forbidden buzzwords from your rollout draft Screening your Chinese draft for forbidden corporate buzzwords Drafting your security trade-off notice for executive review",
            "reply": (
                "[Tier: Deep | Mode: Converge | Confidence Cap: L1]\n"
                "结论：这项要求存在硬冲突，无法按原条件出方案，需请管理层先做取舍。\n"
                "从安全规律看（L1），允许各部门随意直连外部大模型（L4），与“100% 不泄露数据”（L4）直接矛盾。数据一旦离开公司网络边界，技术上就无法保证绝对不泄密；即使上了网关和脱敏，人为复制粘贴或绕道访问仍有残留风险。行业常见的“发制度加装网关”做法只是经验手段（L3），仅在强制收口全部流量时能压低风险；反例是不少企业发了禁令，员工仍用个人账号把源码或合同贴进公网对话页，照样泄密。\n"
                "请老板二选一后再启动：1. 安全优先：关停直连，所有调用经公司统一网关审查，核心数据仅用私有部署模型，接受进度放缓与极低残留风险。2. 效率优先：仅允许用企业零留存协议账号处理公开信息，并明确接受非零泄密风险。"
            ),
        },
    },
}


def run_live_pi(pi_bin: str, prompt: str, use_agents_md: bool, timeout_sec: int = 120) -> str:
    cmd = [pi_bin, "--print", "--approve", "--no-session", "--no-skills"]
    if use_agents_md:
        cmd.extend(["--skill", "./clients/skills/epistemic-dual-process-harness"])
    cmd.append(prompt)
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_sec)
    return proc.stdout.decode("utf-8", errors="replace").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="A/B style & epistemic verifier for TC-07..TC-09")
    parser.add_argument("--cases-file", type=Path, default=DEFAULT_YAML)
    parser.add_argument("--replay", action="store_true", help="Score captured A/B transcripts")
    parser.add_argument("--live", action="store_true", help="Run live A/B via Pi CLI")
    parser.add_argument("--pi-bin", default="pi")
    args = parser.parse_args()

    spec = yaml.safe_load(args.cases_file.read_text(encoding="utf-8"))
    style_rules = spec.get("style_rules", {})
    cases = spec["cases"]

    scores: list[CaseScore] = []
    if args.live:
        for case in cases:
            prompt = case["turns"][0]
            ctrl_reply = run_live_pi(args.pi_bin, prompt, use_agents_md=False)
            trt_reply = run_live_pi(args.pi_bin, prompt, use_agents_md=True)
            scores.append(score_response(case, style_rules, "control_no_agents", ctrl_reply))
            scores.append(score_response(case, style_rules, "treatment_en_agents", trt_reply))
    else:
        for case in cases:
            cid = case["id"]
            for arm, data in REPLAY_TRANSCRIPTS.items():
                entry = data[cid]
                scores.append(
                    score_response(case, style_rules, arm, entry["reply"], entry["thoughts"])
                )

    print(f"{'CASE':<7} {'ARM':<24} {'THOUGHT':<8} {'EPIST':<6} {'BUZZWORDS':<18} {'EN_SLOP':<8} {'PASS'}")
    print("-" * 82)
    for s in scores:
        bw = ",".join(s.zh_buzzwords) if s.zh_buzzwords else "-"
        slop = ",".join(s.en_slop_hits) if s.en_slop_hits else "-"
        print(
            f"{s.case_id:<7} {s.arm:<24} {s.thought_lang:<8} "
            f"{'OK' if s.epistemic_pass else 'FAIL':<6} {bw:<18} {slop:<8} "
            f"{'PASS' if s.passed else 'FAIL'}"
        )

    treatment_ok = all(s.passed for s in scores if "treatment" in s.arm)
    return 0 if treatment_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
