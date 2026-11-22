"""Regression: turn-level dedup + colon-required defect anchors.

Live incident 2026-11-22: one assistant turn accumulated THREE intercept
blocks because the gateway checks at several call sites (non-streaming
initial/retry/final + streaming variants) and the exit gate re-checks at
turn end — none deduplicated, so each site judged text that already carried
a previous site's intercept. Additionally, prose mentions like '缺陷项 P1'
and 'P2 回环' matched the defect-item anchors without declaring anything.
"""

from __future__ import annotations

import importlib.util
import json
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


rg = _load("response_guard_dedup", "proxy_gateway/response_guard.py")
eg = _load("exit_gate_dedup", "orchestrator/exit_gate.py")

VIOLATING_REPLY = (
    "某段缺章节的长回复内容, 足够触发结构检查。" * 24
)
INTERCEPT_TAIL = (
    "\n\n[OUTPUT_CONTRACT_INTERCEPT] 输出契约违规(评审回合):\n"
    "  - P2: 已声明缺陷但缺少验收判据 (验收/acceptance)\n"
    "  - P2: 已声明缺陷但缺少回退路径 (回退/rollback)\n"
    "请按契约重做本回合: 三段式结构 ...\n"
)


class InterceptDedupTests(unittest.TestCase):
    def test_second_check_site_sees_already_judged_text_and_skips(self):
        first = rg.check_response_contract(VIOLATING_REPLY, "system_1_5", "Converge")
        self.assertTrue(first, "first judgement must still fire")
        second = rg.check_response_contract(VIOLATING_REPLY + INTERCEPT_TAIL, "system_1_5", "Converge")
        self.assertEqual(second, [], "already-judged text must not be re-judged")

    def test_exit_gate_turn_end_skips_gateway_judged_text(self):
        self.assertEqual(eg.check_review_completeness(VIOLATING_REPLY + INTERCEPT_TAIL), [])

    def test_prose_mentions_without_colon_do_not_declare_defects(self):
        text = ("表格说明: 缺陷项 P1 是版本号误捕案例; 监控项: P2 回环复现一次即升级调查。\n"
                "均已修复, 无遗留。\n")
        self.assertEqual(rg.check_remediation_completeness(text), [])
        self.assertEqual(eg.check_remediation_completeness(text), [])

    def test_real_colon_declarations_still_caught(self):
        text = "缺陷1: 真实缺陷。\n改动点: 改。\n回退: 可以回退。\n验收: 测试通过即可。\n"
        self.assertTrue(rg.check_remediation_completeness(text))
        self.assertTrue(eg.check_remediation_completeness(text))

    def test_multiplication_scenario_end_to_end(self):
        """Simulate the live incident: site 1 judges, appends; site 2 (turn
        end) must stay silent — total intercepts per turn = 1, not 3."""
        site1 = rg.check_response_contract(VIOLATING_REPLY, "system_1_5", "Converge")
        turn_text = VIOLATING_REPLY + "\n\n" + rg.build_contract_intercept(site1, retry=False)
        site2_gateway = rg.check_response_contract(turn_text, "system_1_5", "Converge")
        site2_engine = eg.check_review_completeness(turn_text)
        self.assertEqual(site2_gateway, [])
        self.assertEqual(site2_engine, [])


if __name__ == "__main__":
    unittest.main()

class InlineCodeMentionTests(unittest.TestCase):
    """Live FP 2026-11-22: discussing the anchor syntax in inline code
    ('`缺陷1:`/`P1:` 才算声明') re-triggered the defect declaration check."""

    MENTION = (
        "修复说明: 现在要求尾冒号, `缺陷1:`/`P1:` 才算声明; 裸提及如 缺陷项 P1 不触发。\n"
        "改动点: 两个镜像模块同步。\n回退: git revert 本提交。\n验收: 新增回归测试 2 项通过。\n"
    )

    def test_inline_code_syntax_mention_not_a_declaration(self):
        self.assertEqual(rg.check_remediation_completeness(self.MENTION), [])
        self.assertEqual(eg.check_remediation_completeness(self.MENTION), [])

    def test_real_declaration_outside_code_still_caught(self):
        text = "缺陷1: 真实缺陷。\n改动点: 改。\n回退: 可以回退。\n验收: 测试通过即可。\n"
        self.assertTrue(rg.check_remediation_completeness(text))
        self.assertTrue(eg.check_remediation_completeness(text))

class InterceptSlimmingAndTracingTests(unittest.TestCase):
    """Compact intercept + forensic tracing (2026-11-22)."""

    def test_compact_intercept_keeps_marker_and_pointer(self):
        text = rg.build_contract_intercept(["v1", "v2", "v3"], retry=True)
        self.assertIn("[OUTPUT_CONTRACT_INTERCEPT]", text)  # dedup marker survives
        self.assertIn("3 项", text)
        self.assertIn("traces/contract_violations.jsonl", text)
        self.assertLessEqual(len(text.splitlines()), 3, "stream carries one compact block")

    def test_violations_are_traced_with_fingerprint(self):
        import json as _json
        import os as _os
        import tempfile as _tf
        with _tf.TemporaryDirectory() as tmp:
            prev = _os.environ.get("HARNESS_TRACES_DIR")  # restore, don't clobber (suite-order coupling)
            _os.environ["HARNESS_TRACES_DIR"] = tmp
            try:
                v = rg.check_response_contract(
                    "缺陷1: 真实缺陷。\n改动点: 改。\n回退: 可以回退。\n验收: 测试通过即可。\n",
                    "system_1_5", "Converge")
                self.assertTrue(v)
                lines = (Path(tmp) / "contract_violations.jsonl").read_text(encoding="utf-8").splitlines()
                self.assertEqual(len(lines), 1)
                rec = _json.loads(lines[0])
                self.assertEqual(rec["layer"], "gateway")
                self.assertEqual(rec["n_violations"], len(v))
                self.assertEqual(len(rec["text_sha256"]), 64)
                self.assertTrue(rec["code_rev"])
            finally:
                if prev is None:
                    _os.environ.pop("HARNESS_TRACES_DIR", None)
                else:
                    _os.environ["HARNESS_TRACES_DIR"] = prev

    def test_dedup_still_works_with_compact_intercept(self):
        site1 = rg.check_response_contract(VIOLATING_REPLY, "system_1_5", "Converge")
        self.assertTrue(site1)
        turn_text = VIOLATING_REPLY + "\n\n" + rg.build_contract_intercept(site1, retry=False)
        self.assertEqual(rg.check_response_contract(turn_text, "system_1_5", "Converge"), [])
        self.assertEqual(eg.check_review_completeness(turn_text), [])

class ReviewCheckCliTests(unittest.TestCase):
    """exit_gate.py --review-check: the TS turn-end guard's judgment entry."""

    def _run_cli(self, text: str) -> dict:
        import subprocess as sp
        proc = sp.run(
            [sys.executable, str(PACK_ROOT / "orchestrator" / "exit_gate.py"), "--review-check"],
            input=text, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        return json.loads(proc.stdout)

    def test_cli_flags_violations_and_builds_bounce(self):
        out = self._run_cli(
            "[Tier: Structured Analysis | Mode: Converge | Confidence Cap: L2]\n"
            "## 核心结论\nx\n## 认识论分解\n[L3] 经验。\n## 证据缺口\n无。\n"
        )
        self.assertTrue(any("silent promotion" in v for v in out["violations"]))
        # TS wraps this payload with the [HARNESS_REVIEW_GATE_RETRY] prefix
        self.assertIn("[REVIEW_CONTRACT_INTERCEPT]", out["bounce_retry"])

    def test_cli_clean_text_no_bounce(self):
        out = self._run_cli("全部测试通过, 已验证, 无遗留。\n")
        self.assertEqual(out["violations"], [])
        self.assertEqual(out["bounce_retry"], "")

    def test_cli_dedup_already_judged_text(self):
        text = (
            "[Tier: Structured Analysis | Mode: Converge | Confidence Cap: L2]\n"
            "## 核心结论\nx\n## 认识论分解\n[L3] 经验。\n适用: s。反例: c。\n## 证据缺口\n无。\n"
            "\n\n[OUTPUT_CONTRACT_INTERCEPT] 输出契约违规 1 项; 首条: silent promotion\n"
        )
        out = self._run_cli(text)
        self.assertEqual(out["violations"], [])
