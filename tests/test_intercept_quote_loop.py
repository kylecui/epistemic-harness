"""Regression: quoting an intercept/bounce block must not re-trigger the
checks it describes (live self-reference loop, 2026-11-22: the gateway's own
intercept text appended to a reply re-flagged '缺陷1:' bullets when quoted).

Also: short status/verification replies (<400 chars, no epistemic markers)
skip the three-section deliverable anchors; cap and L3 checks still apply.
"""

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


rg = _load("response_guard_fp", "proxy_gateway/response_guard.py")
eg = _load("exit_gate_fp", "orchestrator/exit_gate.py")

QUOTED_INTERCEPT = (
    "网关刚才返回了这段, 我确认已处理:\n"
    "[OUTPUT_CONTRACT_INTERCEPT] 输出契约违规(评审回合):\n"
    "  - 缺陷1: 已声明缺陷但缺少验收判据 (验收/acceptance)\n"
    "  - 缺陷1: 已声明缺陷但缺少回退路径 (回退/rollback)\n"
    "请按契约重做本回合: 三段式结构 ...\n"
    "处理完毕, 两条都已修复。\n"
)

STATUS_REPLY = (
    "[Tier: Reflexive Execution | Mode: Converge]\n"
    "红灯已修复: eol 归一完成, docs fresh (v0.5.0), 254 项测试 OK, 工作树干净。\n"
    "失败归属: 工具事故, 非代码缺陷。\n"
    "- eol_policy: ok\n- docs_fresh: ok\n- routing: ok\n"
)


class InterceptQuoteLoopTests(unittest.TestCase):
    def test_quoted_intercept_does_not_retrigger_gateway(self):
        self.assertEqual(rg.check_remediation_completeness(QUOTED_INTERCEPT), [])
        self.assertEqual(rg.check_output_structure(QUOTED_INTERCEPT, "system_1_5", "Converge"), [])

    def test_quoted_intercept_does_not_retrigger_exit_gate(self):
        self.assertEqual(eg.check_remediation_completeness(QUOTED_INTERCEPT), [])
        self.assertEqual(eg.check_review_completeness(QUOTED_INTERCEPT), [])

    def test_genuine_defect_declaration_still_caught_when_not_quoted(self):
        text = "缺陷1: 真实缺陷。\n改动点: 改。\n回退: 可以回退。\n验收: 测试通过即可。\n"
        self.assertTrue(rg.check_remediation_completeness(text))
        self.assertTrue(eg.check_remediation_completeness(text))

    def test_short_status_reply_skips_section_anchors_but_keeps_l3_and_cap(self):
        self.assertEqual(rg.check_output_structure(STATUS_REPLY, "system_1_5", "Converge"), [])

    def test_long_or_marker_bearing_reply_still_needs_sections(self):
        long_text = STATUS_REPLY + ("补充说明行。" * 60)
        v = rg.check_output_structure(long_text, "system_1_5", "Converge")
        self.assertTrue(any("三段式" in x for x in v))
        marked = STATUS_REPLY + "\n[L2] 依据来自代码。\n"
        v2 = rg.check_output_structure(marked, "system_1_5", "Converge")
        self.assertTrue(any("三段式" in x for x in v2))


if __name__ == "__main__":
    unittest.main()
