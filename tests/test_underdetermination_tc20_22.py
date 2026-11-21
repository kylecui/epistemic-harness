"""TC-20..TC-22 — issue #3: no fabricated decision points + research grounding.

Both layers are covered because they are mirrored in code:
  * proxy_gateway/response_guard.py  (gateway boundary)
  * orchestrator/exit_gate.py        (headless / MCP boundary)
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

PACK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK_ROOT))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, PACK_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rg = _load("rg_underdet", "proxy_gateway/response_guard.py")
eg = _load("eg_underdet", "orchestrator/exit_gate.py")

FABRICATED = """
## 核心结论
字典里 zh 值是中文，属于正常翻译内容。

## 认识论分解
[L2] 现有扫描脚本按 node 类型排除 i18n 节点。

## 证据缺口
有一处边界需要你来拍板：字典 zh 值写中文到底算不算硬编码。
"""

GENUINE_L4 = """
## 核心结论
建议保留现有扫描规则。

## 认识论分解
[L2] 扫描脚本已排除 i18n 节点。

## 证据缺口
需要你拍板：是否允许对历史数据做永久处置。这是 L4 风险取舍（预算与合规由你方承担）。
"""

GENUINE_L2_GAP = """
## 核心结论
当前无法判定线上真实分布。

## 认识论分解
[L3] 内存页命中率通常高于磁盘页 — 适用：热数据场景；反例：冷数据批量扫描。

## 证据缺口
需要你确认：是否提供生产日志。缺少 L2 证据（未检索、无日志）前我不下结论。
"""


class UnderdeterminationTests(unittest.TestCase):
    """TC-20/21: the same verdict must come out of both enforcement layers."""

    def test_tc20_fabricated_decision_point_is_flagged_by_both_layers(self):
        for mod in (rg, eg):
            violations = mod.check_underdetermination(FABRICATED)
            self.assertTrue(violations, f"{mod.__name__}: fabricated decision point must be flagged")
            self.assertIn("伪决策点", violations[0])

    def test_tc21_l4_tradeoff_decision_point_passes(self):
        for mod in (rg, eg):
            self.assertEqual(mod.check_underdetermination(GENUINE_L4), [], mod.__name__)

    def test_tc21b_missing_l2_evidence_passes(self):
        for mod in (rg, eg):
            self.assertEqual(mod.check_underdetermination(GENUINE_L2_GAP), [], mod.__name__)

    def test_quoted_material_is_exempt(self):
        text = "用户原话：\n> 这里到底该不该由我决定\n以上是引用。"
        for mod in (rg, eg):
            self.assertEqual(mod.check_underdetermination(text), [], mod.__name__)

    def test_review_turn_bounces_on_fabricated_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = eg.ExitGateEngine(repo_dir=Path(tmp))
            decision = engine.evaluate(FABRICATED, mutated_this_turn=False)
            self.assertFalse(decision.passed)
            self.assertEqual(decision.action, "bounce")
            self.assertTrue(any("伪决策点" in v for v in decision.contract_violations))


class ResearchGroundingTests(unittest.TestCase):
    """The research discipline must be checkable, not just written in the contract."""

    def test_unanchored_sota_claim_is_flagged(self):
        text = "记忆方案建议用图数据库，这是目前业界标准的做法。"
        for mod in (rg, eg):
            self.assertTrue(mod.check_external_grounding(text), mod.__name__)

    def test_source_anchor_satisfies_the_rule(self):
        text = "图记忆在长程任务上更好（arXiv:2611.25123，检索于 2026-11-20）。"
        for mod in (rg, eg):
            self.assertEqual(mod.check_external_grounding(text), [], mod.__name__)

    def test_explicit_no_search_declaration_satisfies_the_rule(self):
        text = "最流行的做法是向量检索（未检索，凭记忆，置信上限按 L3 处理）。"
        for mod in (rg, eg):
            self.assertEqual(mod.check_external_grounding(text), [], mod.__name__)

    def test_plain_answer_without_superlatives_is_untouched(self):
        text = "这个函数返回 int，改个名字即可。"
        self.assertEqual(rg.check_external_grounding(text), [])


if __name__ == "__main__":
    unittest.main()
