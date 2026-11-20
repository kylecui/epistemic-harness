"""Unit tests for review-turn contract checks (issue #1, TC-12..TC-15).

Covers:
  * proxy_gateway/response_guard.py — structure / silent-promotion /
    remediation-completeness pure checks driven by the golden cases in
    `evals/golden_cases_review_completeness.yaml`.
  * orchestrator/exit_gate.py — the same-structure engine: non-mutated review
    turns are no longer auto-pass; bounce at most once, then halt to user.
  * False-positive guards: plain Q&A, status reports, and the compliant
    "证据缺口 & Complete Remediation Plan" section header alone must not
    trigger the defect check.
"""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

import yaml

PACK_ROOT = Path(__file__).resolve().parent.parent
RESPONSE_GUARD_PATH = PACK_ROOT / "proxy_gateway" / "response_guard.py"
EXIT_GATE_PATH = PACK_ROOT / "orchestrator" / "exit_gate.py"
GOLDEN_PATH = PACK_ROOT / "evals" / "golden_cases_review_completeness.yaml"
sys.path.insert(0, str(PACK_ROOT))


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rg = _load_module("response_guard", RESPONSE_GUARD_PATH)
eg = _load_module("exit_gate", EXIT_GATE_PATH)

CASES = {c["id"]: c for c in yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8"))["cases"]}


class GoldenCaseTests(unittest.TestCase):
    """TC-12..TC-15: golden cases must produce exactly the expected verdicts."""

    def _run(self, case_id: str) -> list[str]:
        case = CASES[case_id]
        text = case["assistant_text"]
        if case["check"] == "remediation":
            return rg.check_remediation_completeness(text)
        return rg.check_output_structure(text, case.get("tier", ""), case.get("mode", ""))

    def test_tc12_defect_downgrade_intercepted(self):
        violations = self._run("TC-12")
        self.assertTrue(violations, "TC-12: downgrade to '补一段文档' must be intercepted")
        joined = "\n".join(violations)
        for expected in CASES["TC-12"]["expected_violations"]:
            self.assertIn(expected, joined)

    def test_tc13_custom_sections_intercepted(self):
        violations = self._run("TC-13")
        self.assertTrue(violations, "TC-13: Converge without contract anchors must be intercepted")
        self.assertIn("缺少三段式锚点", "\n".join(violations))

    def test_tc14_silent_promotion_intercepted(self):
        violations = self._run("TC-14")
        self.assertTrue(any("silent promotion" in v for v in violations),
                        f"TC-14: header L2 over L3 body must be flagged, got {violations}")

    def test_tc15_l4_tradeoff_not_intercepted(self):
        violations = self._run("TC-15")
        self.assertEqual(violations, [], f"TC-15: review-only L4 trade-off must pass, got {violations}")

    def test_golden_cases_match_expected_verdicts(self):
        for case_id, case in CASES.items():
            with self.subTest(case=case_id):
                violations = self._run(case_id)
                self.assertEqual(bool(violations), case["expect_violation"],
                                 f"{case_id} verdict mismatch: {violations}")


class FalsePositiveTests(unittest.TestCase):
    """Anti-false-positive branches required by issue #1."""

    def test_plain_qa_not_checked(self):
        text = "直接把 MAX_RETRY_COUNT 转成小驼峰: maxRetryCount。完毕。"
        self.assertEqual(rg.check_remediation_completeness(text), [])
        self.assertEqual(rg.check_output_structure(text, "system_0", "Explore"), [])

    def test_gaps_section_header_alone_is_not_a_defect(self):
        # The compliant contract section header mentions 证据缺口 but declares
        # no numbered defect item: must not trigger the remediation check.
        text = (
            "[Tier: 结构化分析 | Mode: Converge | Confidence Cap: L2]\n"
            "## 核心结论\n无阻塞问题。\n"
            "## 认识论分解\n[L2] 全部依据来自代码与日志。\n"
            "## 证据缺口\n无。"
        )
        self.assertEqual(rg.check_remediation_completeness(text), [])

    def test_compliant_defect_plan_passes(self):
        text = (
            "## 证据缺口 & Complete Remediation Plan\n"
            "缺陷1: 主键变化导致旧二进制在新表产生重复行。\n"
            "改动点: schema 迁移加唯一约束; 迁移影响: 需清表重灌; "
            "回退: 回滚迁移并恢复快照; 验收: 升级后重复行数为 0 的单测。\n"
            "缺陷2: 提权信号可被诱导抑制。\n"
            "改动点: 信号计数器改为单调累加; 回退: 特性开关关闭; "
            "验收: 诱导输入下信号仍触发的集成测试。\n"
        )
        self.assertEqual(rg.check_remediation_completeness(text), [])

    def test_tier1_explore_unstructured_ok(self):
        text = "随便聊聊, 没有结论结构。"
        self.assertEqual(rg.check_output_structure(text, "system_1", "Explore"), [])


class ExitGateReviewTurnTests(unittest.TestCase):
    """orchestrator/exit_gate.py: review turns (zero file changes) are gated."""

    def _engine(self) -> "eg.ExitGateEngine":
        return eg.ExitGateEngine(repo_dir=Path(tempfile.gettempdir()), checks=[])

    DOWNGRADING_REVIEW = (
        "缺陷1: 新报文路径绕过段内过滤。\n最小后续动作: 补一段文档。\n"
    )
    CLEAN_REVIEW = (
        "## 核心结论\n接口正常。\n## 认识论分解\n[L2] 日志核实。\n## 证据缺口\n无。\n"
    )
    COMPLIANT_DEFECT_REVIEW = (
        "## 证据缺口 & Complete Remediation Plan\n"
        "缺陷1: 路径绕过过滤。改动点: net/filter.py:88 加归属判断; "
        "迁移影响: 无; 回退: revert 该提交; 验收: 外部报文标记为外部的单测。\n"
    )

    def test_downgrading_review_bounced_once_then_halt(self):
        engine = self._engine()
        d1 = engine.evaluate(self.DOWNGRADING_REVIEW, mutated_this_turn=False)
        self.assertFalse(d1.passed)
        self.assertEqual(d1.action, "bounce")
        self.assertTrue(d1.contract_violations)
        self.assertIn("缺陷降级", "\n".join(d1.contract_violations))

        d2 = engine.evaluate(self.DOWNGRADING_REVIEW, mutated_this_turn=False)
        self.assertFalse(d2.passed)
        self.assertEqual(d2.action, "halt_to_user")
        self.assertIn("ESCALATE_TO_L2", d2.bounce_prompt)

    def test_clean_review_passes_and_resets_counter(self):
        engine = self._engine()
        d = engine.evaluate(self.CLEAN_REVIEW, mutated_this_turn=False)
        self.assertTrue(d.passed)
        self.assertEqual(engine.review_retry_count, 0)

    def test_compliant_defect_plan_passes_on_review_turn(self):
        engine = self._engine()
        d = engine.evaluate(self.COMPLIANT_DEFECT_REVIEW, mutated_this_turn=False)
        self.assertTrue(d.passed, f"compliant plan must pass, got {d.contract_violations}")

    def test_mutated_turn_resets_review_counter(self):
        engine = self._engine()
        engine.evaluate(self.DOWNGRADING_REVIEW, mutated_this_turn=False)
        engine.evaluate("done", mutated_this_turn=True)  # green mutated turn
        self.assertEqual(engine.review_retry_count, 0)

    def test_no_defect_review_turn_passes(self):
        engine = self._engine()
        d = engine.evaluate(self.CLEAN_REVIEW, mutated_this_turn=False)
        self.assertTrue(d.passed)


class GatewayIntegrationTests(unittest.TestCase):
    """End-to-end through create_app: the intercept bounce really happens."""

    def _client(self, handler) -> tuple[TestClient, QuotaManager]:
        from fastapi.testclient import TestClient
        import httpx
        from proxy_gateway.app import create_app
        from proxy_gateway.quota_manager import QuotaManager
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        qm = QuotaManager(PACK_ROOT / "proxy_gateway" / "quota_policy.yaml", Path(tmp.name) / "q.db")
        now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
        app = create_app(
            openai_upstream="https://mock.local/v1",
            transport=httpx.MockTransport(handler),
            quota_manager=qm,
            now_provider=lambda: now,
        )
        return TestClient(app), qm

    def test_downgrading_review_gets_one_corrective_retry(self):
        from datetime import datetime, timezone
        calls: list[dict] = []
        bad = (
            "[Tier: 结构化分析 | Mode: Converge | Confidence Cap: L2]\n"
            "一、评审发现\n"
            "缺陷1: 新增报文归属路径绕过段内过滤, 外部报文可被标记为内部来源, "
            "影响范围覆盖全部新接入链路, 属于安全目标违背。\n"
            "二、处置建议\n"
            "最小后续动作: 补一段文档说明该限制; 写进已知问题清单即可。\n"
        )
        good = (
            "[Tier: 结构化分析 | Mode: Converge | Confidence Cap: L3]\n"
            "## 核心结论\n缺陷成立, 交付完整方案。\n"
            "## 认识论分解\n[L3] 适用: 基于代码路径推演; 反例: 若网关已归一化则不成立。\n"
            "## 证据缺口 & Complete Remediation Plan\n"
            "缺陷1: 路径绕过过滤。改动点: net/filter.py:88 加归属判断; "
            "迁移影响: 无; 回退: revert 该提交; 验收: 外部报文不被标记为内部的单测。\n"
        )

        async def handler(request):
            import httpx
            body = json.loads(request.content.decode("utf-8"))
            calls.append(body)
            content = bad if len(calls) == 1 else good
            return httpx.Response(200, json={
                "id": "ok",
                "choices": [{"message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            })

        client, _ = self._client(handler)
        resp = client.post(
            "/v1/chat/completions",
            json={"stream": False, "messages": [{"role": "user", "content": "请收敛审计这次代码评审的缺陷"}]},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(calls), 2, "exactly one corrective retry must fire")
        self.assertIn("Complete Remediation Plan", resp.json()["choices"][0]["message"]["content"])
        self.assertNotIn("OUTPUT_CONTRACT_INTERCEPT", resp.json()["choices"][0]["message"]["content"])

    def test_short_ack_no_retry_no_intercept(self):
        from datetime import datetime, timezone
        calls: list[dict] = []

        async def handler(request):
            import httpx
            calls.append(json.loads(request.content.decode("utf-8")))
            return httpx.Response(200, json={
                "id": "ok",
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            })

        client, _ = self._client(handler)
        resp = client.post(
            "/v1/chat/completions",
            json={"stream": False, "messages": [{"role": "user", "content": "请收敛审计"}]},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(calls), 1, "short acknowledgements must not trigger a retry")
        content = resp.json()["choices"][0]["message"]["content"]
        self.assertTrue(content.startswith("[Tier:"), "tier tag injection is existing behavior")
        self.assertTrue(content.endswith("ok"))
        self.assertNotIn("OUTPUT_CONTRACT_INTERCEPT", content)


    @staticmethod
    def _openai_sse(content: str):
        import httpx
        chunks = [
            {"id": "c1", "choices": [{"index": 0, "delta": {"content": content}}]},
            {"id": "c1", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        ]
        body = "".join(f"data: {json.dumps(c, ensure_ascii=False)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, text=body)

    def test_streaming_intercept_injected_before_done(self):
        bad = (
            "[Tier: 结构化分析 | Mode: Converge | Confidence Cap: L2]\n"
            "一、评审发现\n"
            "缺陷1: 新增报文归属路径绕过段内过滤, 外部报文可被标记为内部来源, "
            "影响范围覆盖全部新接入链路, 属于安全目标违背。\n"
            "二、处置建议\n"
            "最小后续动作: 补一段文档说明该限制; 写进已知问题清单即可。\n"
        )

        async def handler(request):
            return self._openai_sse(bad)

        client, _ = self._client(handler)
        with client.stream(
            "POST", "/v1/chat/completions",
            json={"stream": True, "messages": [{"role": "user", "content": "请收敛审计这次评审"}]},
        ) as resp:
            body = "".join(resp.iter_text())
        self.assertEqual(body.count("data: [DONE]"), 1, "[DONE] must be emitted exactly once")
        self.assertIn("OUTPUT_CONTRACT_INTERCEPT", body)
        self.assertLess(
            body.index("OUTPUT_CONTRACT_INTERCEPT"), body.index("data: [DONE]"),
            "intercept must be injected before [DONE]",
        )

    def test_streaming_short_stream_clean(self):
        async def handler(request):
            return self._openai_sse("ok")

        client, _ = self._client(handler)
        with client.stream(
            "POST", "/v1/chat/completions",
            json={"stream": True, "messages": [{"role": "user", "content": "请收敛审计"}]},
        ) as resp:
            body = "".join(resp.iter_text())
        self.assertEqual(body.count("data: [DONE]"), 1)
        self.assertNotIn("OUTPUT_CONTRACT_INTERCEPT", body)


if __name__ == "__main__":
    unittest.main()
