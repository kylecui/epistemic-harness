"""Hollow-compliance adversarial suite (review defect #2, 2026-11-22).

Each HOLLOW reply satisfies the OLD anchor-word checks (every regex hit present)
while carrying zero substance: filler scope/counter-example phrases, unfalsifiable
acceptance ("测试通过即可"), tautological rollback ("可以回退"). Under the
strengthened checks every one of them must produce >= 1 violation in BOTH the
gateway (proxy_gateway/response_guard.py) and headless
(orchestrator/exit_gate.py) implementations.

Each SOLID reply is the same shape with real content and must stay clean in both.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
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


rg = _load("response_guard_hollow", "proxy_gateway/response_guard.py")
eg = _load("exit_gate_hollow", "orchestrator/exit_gate.py")

TIER_TAG = "[Tier: 结构化分析 | Mode: Converge | Confidence Cap: L3]\n"

HOLLOW: list[tuple[str, str]] = [
    ("filler_scope_counter", TIER_TAG + "## 认识论分解\n[L3] 微服务先行。\n适用: 各种情况。\n反例: 有些情况不适用。\n"),
    ("boilerplate_scope", TIER_TAG + "[L3] 试用期调整。\n适用: 视情况而定。\n反例: 因情况而异。\n"),
    ("unfalsifiable_acceptance",
     "缺陷1: 索引缺失导致查询慢。\n改动点: 加索引。\n回退: 删除索引即可。\n验收: 测试通过即可。\n"),
    ("tautological_rollback",
     "缺陷1: 缓存穿透。\n改动点: 加布隆过滤器。\n回退: 可以回退。\n验收: 压测 p99 降至 200ms 以内的报告。\n"),
    ("numeric_only_filler",
     "缺陷1: 重复消息。\n改动点: 加幂等键。\n回退: 必要时回退。\n验收: 符合预期。\n"),
    ("na_rollback",
     "缺陷1: 越权读取。\n改动点: 补权限校验。\n回退: n/a。\n验收: 单测覆盖越权用例。\n"),
    ("maybe_acceptance",
     "缺陷1: 时区错乱。\n改动点: 统一存 UTC。\n回退: git revert 迁移提交。\n验收: 也许没问题。\n"),
    ("empty_structured",
     '```harness-claim\n[{"defect": "x", "fix_points": "改一下", "rollback": "回退", "acceptance": "通过"}]\n```\n'),
    ("hollow_structured",
     '```harness-claim\n{"defect": "有问题", "fix_points": "处理一下", "rollback": "可以回退", "acceptance": "测试通过即可"}\n```\n'),
    ("defect_only_words",
     "缺陷1: 有问题。\n改动点: 改一改。\n回退: 回退回去。\n验收: 看看就行。\n"),
]

SOLID: list[tuple[str, str]] = [
    ("solid_prose",
     TIER_TAG + "## 核心结论\n修复方案如下。\n## 认识论分解\n[L2] 依据代码与日志。\n## 证据缺口\n无。\n"
     "缺陷1: 主键变化导致旧二进制在新表产生重复行。\n"
     "改动点: schema 迁移加唯一约束; 迁移影响: 需清表重灌; "
     "回退: git revert 迁移提交并恢复昨晚快照; 验收: 升级后重复行数为 0 的 unittest。\n"),
    ("solid_structured",
     '```harness-claim\n{"defect": "旧缓存键与新序列化格式不兼容导致反序列化失败", '
     '"fix_points": "升级读路径先做格式探测再解码", '
     '"rollback": "特性开关 rollback_legacy_decoder=true 并重新部署上一版本镜像", '
     '"acceptance": "混合键流量下错误率为 0, 由集成测试断言"}\n```\n'),
    ("solid_l3_tags",
     TIER_TAG + "## 核心结论\n按 L3 假设处理。\n## 认识论分解\n"
     "[L3] 模块化单体优先。\n适用: 15 人以下团队、流量中小、业务验证期。\n"
     "反例: 客户强制私有化 Helm 交付时需独立模块。\n"
     "## 证据缺口\n缺少 A/B 数据。\n"),
]


class HollowComplianceAdversarialTests(unittest.TestCase):
    def test_hollow_replies_flagged_in_both_implementations(self) -> None:
        misses: list[str] = []
        for name, text in HOLLOW:
            v_rg = rg.check_review_completeness(text) if hasattr(rg, "check_review_completeness") else (
                rg.check_output_structure(text, "system_1_5", "Converge")
                + rg.check_remediation_completeness(text)
                + rg.check_underdetermination(text)
                + rg.check_external_grounding(text)
            )
            v_eg = eg.check_review_completeness(text)
            if not v_rg:
                misses.append(f"{name}: gateway response_guard passed hollow reply")
            if not v_eg:
                misses.append(f"{name}: exit_gate passed hollow reply")
        self.assertEqual(misses, [], "\n".join(misses))

    def test_solid_replies_still_clean_in_both_implementations(self) -> None:
        for name, text in SOLID:
            v_rg = (
                rg.check_output_structure(text, "system_1_5", "Converge")
                + rg.check_remediation_completeness(text)
                + rg.check_underdetermination(text)
                + rg.check_external_grounding(text)
            )
            v_eg = eg.check_review_completeness(text)
            self.assertEqual(v_rg, [], f"{name}: gateway false-positive: {v_rg}")
            self.assertEqual(v_eg, [], f"{name}: exit_gate false-positive: {v_eg}")


if __name__ == "__main__":
    unittest.main()
