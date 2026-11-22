"""Regression: 'P1.6'-style version/milestone headers must not be read as
declared defect items (live gateway false positive, 2026-11-22)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
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


rg = _load("response_guard_pver", "proxy_gateway/response_guard.py")
eg = _load("exit_gate_pver", "orchestrator/exit_gate.py")

PROGRESS_TEXT = (
    "P1.6 已完成: hollow_audit 模块落地, 测试 4 项全绿。\n"
    "P1.7 进行中: 记忆有效性实验。\n"
    "下一步 P2.8 多语言锚点。\n"
)


class PNumberFalsePositiveTests(unittest.TestCase):
    def test_version_headers_not_defect_items(self):
        self.assertEqual(rg.check_remediation_completeness(PROGRESS_TEXT), [])
        self.assertEqual(eg.check_remediation_completeness(PROGRESS_TEXT), [])

    def test_real_defect_items_still_detected(self):
        text = "P1: 缓存击穿风险未处理。\n改动点: 加布隆过滤器。\n回退: git revert。\n验收: 穿透请求数为 0 的单测。\n"
        self.assertEqual(rg.check_remediation_completeness(text), [])
        self.assertEqual(eg.check_remediation_completeness(text), [])

    def test_p12_project_anchor_still_detected(self):
        text = "P12: 主键变化导致重复行。\n改动点: 加唯一约束。\n回退: git revert 迁移。\n验收: 重复行数为 0。\n"
        self.assertEqual(rg.check_remediation_completeness(text), [])


if __name__ == "__main__":
    unittest.main()
