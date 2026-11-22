"""Multilingual anchor coverage (P2.8, 2026-11-22): ja/ko hollow replies must
trip the same substance checks as zh/en ones."""

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


rg = _load("response_guard_i18n", "proxy_gateway/response_guard.py")
eg = _load("exit_gate_i18n", "orchestrator/exit_gate.py")

JA_HOLLOW = (
    "[Tier: Structured Analysis | Mode: Converge | Confidence Cap: L3]\n"
    "## 核心结论\n"
    "[L3] マイクロサービス先行。\n"
    "適用: 場合による。\n"
    "反例: 例外ケースもある。\n"
)
JA_SOLID = (
    "[Tier: Structured Analysis | Mode: Converge | Confidence Cap: L3]\n"
    "## 核心结论\n結論。\n## 认识论分解\n"
    "[L3] モノリス優先。\n"
    "適用: 15人未満のチーム、中小トラフィック。\n"
    "反例: 顧客がHelm配布を要求する場合は除く。\n"
    "## 证据缺口\n无。\n"
)
KO_SOLID_DEFECT = (
    "缺陷1: 재고 미확인 주문 접수。\n"
    "改动点: 재고 확인 로직 추가。\n"
    "回退: 롤백은 git revert와 백업 스냅샷으로 수행。\n"
    "验收: 재고 0 건에서 주문이 거부되는 단위 테스트 3건。\n"
)
KO_HOLLOW_DEFECT = (
    "缺陷1: 재고 미확인 주문 접수。\n"
    "改动点: 고친다。\n"
    "回退: 롤백 가능。\n"
    "验收: 테스트 통과。\n"
)


class MultilingualAnchorTests(unittest.TestCase):
    def test_ja_hollow_l3_flagged(self):
        self.assertTrue(rg.check_output_structure(JA_HOLLOW, "system_1_5", "Converge"))
        self.assertTrue(eg.check_l3_scope(JA_HOLLOW))

    def test_ja_solid_l3_clean(self):
        self.assertEqual(rg.check_output_structure(JA_SOLID, "system_1_5", "Converge"), [])
        self.assertEqual(eg.check_l3_scope(JA_SOLID), [])

    def test_ko_solid_defect_plan_passes(self):
        self.assertEqual(rg.check_remediation_completeness(KO_SOLID_DEFECT), [])
        self.assertEqual(eg.check_remediation_completeness(KO_SOLID_DEFECT), [])

    def test_ko_hollow_defect_plan_flagged(self):
        self.assertTrue(rg.check_remediation_completeness(KO_HOLLOW_DEFECT))
        self.assertTrue(eg.check_remediation_completeness(KO_HOLLOW_DEFECT))

    def test_ja_shirking_phrases_detected(self):
        self.assertTrue(eg.detect_shirking("この失敗は既存の問題なので今回は対象外とする"))
        self.assertTrue(eg.detect_shirking("이번 실패는 기존 문제로 이번 변경과 무관"))


if __name__ == "__main__":
    unittest.main()
