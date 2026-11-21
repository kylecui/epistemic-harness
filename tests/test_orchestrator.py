import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

import httpx

from tests.sse_util import sse_response
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# run_plan registers L5 claims; those must never land in the repo's real memory
# store. The env var is read when EpistemicEngine is constructed.
os.environ.setdefault("HARNESS_MEMORY_STORE", tempfile.mkdtemp(prefix="harness-test-store-"))

from orchestrator.bias_guard import BiasGuard
from orchestrator.dispatch import dispatch_subtask
from orchestrator.planner import classify_task
from orchestrator.server import Orchestrator, handle_request
from orchestrator.skills import SkillRegistry


class TestPlanner(unittest.TestCase):
    def test_classify_maps_tiers_to_profiles(self) -> None:
        self.assertEqual(classify_task("把 MAX_RETRY 转成 camelCase，直接给我结果")["agent_profile"], "explorer")
        self.assertEqual(classify_task("分析一下这个 5 人团队的后端架构选型")["agent_profile"], "coder")
        self.assertEqual(classify_task("用 CAP 定理形式化证明网络分区下 C 与 A 不可兼得")["agent_profile"], "deep")
        self.assertEqual(classify_task("请对前面的推导做独立复核和元认知审计")["agent_profile"], "critic")

    def test_classify_attaches_matching_skills(self) -> None:
        registry = SkillRegistry(REPO_ROOT / "skills" / "registry.yaml", REPO_ROOT / "skill_queue" / "pending.yaml")
        result = classify_task("帮我 review 这段代码的 diff，做 code review", skills_matcher=registry.match_for_task)
        attached = [s["id"] for s in result["auto_attached_skills"]]
        self.assertIn("SKILL-CODE-REVIEW", attached)


class TestSkillRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = REPO_ROOT / "tests" / "_tmp_skill_queue.yaml"
        if self.tmp.exists():
            self.tmp.unlink()
        self.registry = SkillRegistry(REPO_ROOT / "skills" / "registry.yaml", self.tmp)

    def tearDown(self) -> None:
        if self.tmp.exists():
            self.tmp.unlink()

    def test_query_matches_triggers(self) -> None:
        hits = self.registry.query("根因 排查")
        self.assertEqual(hits[0]["id"], "SKILL-ROOT-CAUSE-TRIAGE")

    def test_register_queues_for_human_approval(self) -> None:
        res = self.registry.register_pending(
            name="sql-tuning", description="Index-first SQL tuning checklist", content="1. EXPLAIN first."
        )
        self.assertEqual(res["queued"]["status"], "awaiting_human_approval")
        queued = yaml.safe_load(self.tmp.read_text(encoding="utf-8"))["pending_skills"]
        self.assertEqual(len(queued), 1)
        self.assertNotIn("SKILL-PENDING-001", self.registry.skills)  # live registry untouched


class TestDispatch(unittest.TestCase):
    def test_dispatch_sends_profile_headers_and_skill_preamble(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(request.headers)
            captured["payload"] = json.loads(request.content.decode("utf-8"))
            return sse_response("sub-result", model="kimi-for-coding")

        result = dispatch_subtask(
            agent_profile="coder",
            task_text="排查线上报错，先做根因初筛",
            context="controller context here",
            task_id="T-001",
            gateway_url="http://mock.local",
            attached_skills=[{"name": "root-cause-triage", "content": "[Skill] collect L2 first."}],
            transport=httpx.MockTransport(handler),
        )
        self.assertEqual(result["content"], "sub-result")
        self.assertEqual(result["routed_tier"], "system_1_5")
        self.assertEqual(captured["headers"]["x-harness-agent-id"], "coder")
        self.assertEqual(captured["headers"]["x-harness-session-id"], "T-001")
        system_msg = captured["payload"]["messages"][0]["content"]
        self.assertIn("[Attached Skill: root-cause-triage]", system_msg)
        self.assertIn("controller context here", captured["payload"]["messages"][1]["content"])


class TestOrchestratorMCP(unittest.TestCase):
    def setUp(self) -> None:
        self.orch = Orchestrator(REPO_ROOT)

    def _call(self, name: str, args: dict) -> dict:
        resp = handle_request(self.orch, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": args},
        })
        self.assertNotIn("error", resp)
        self.assertFalse(resp["result"]["isError"], resp["result"]["content"][0]["text"])
        return json.loads(resp["result"]["content"][0]["text"])

    def test_classify_task_tool(self) -> None:
        res = self._call("classify_task", {"task_text": "用 CAP 定理形式化证明一致性约束"})
        self.assertEqual(res["agent_profile"], "deep")

    def test_submit_and_audit_shared_engine(self) -> None:
        self._call("submit_l5_claim", {
            "claim_id": "L5-ORCH-1",
            "claim": "test claim",
            "claimed_tier": "L2",
            "source_ids": ["L1-CAP-001"],
        })
        audit = self._call("audit_dag", {})
        self.assertEqual(audit["overall_confidence_cap"], "L1")

    def test_tools_list_exposes_orchestration(self) -> None:
        resp = handle_request(self.orch, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = [t["name"] for t in resp["result"]["tools"]]
        for expected in ("classify_task", "dispatch_subagent", "query_skills", "register_skill", "audit_dag"):
            self.assertIn(expected, names)


if __name__ == "__main__":
    unittest.main()


class TestBiasGuard(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(__file__).resolve().parent.parent
        self.guard = BiasGuard(self.repo / "knowledge" / "l3_heuristics" / "cognitive_biases.yaml")

    def test_catalog_loads_with_mandatory_l3_fields(self) -> None:
        self.assertGreaterEqual(len(self.guard.biases), 8)
        for bias in self.guard.biases.values():
            self.assertTrue(bias["scope_conditions"])
            self.assertTrue(bias["counter_examples"])
            self.assertTrue(bias["correction"])

    def test_scan_detects_overconfidence_marker(self) -> None:
        res = self.guard.scan("这个方案绝对可行，百分之百没问题，肯定能上线。")
        ids = [m["bias_id"] for m in res["matches"]]
        self.assertIn("BIAS-OVERCONFIDENCE", ids)
        self.assertEqual(res["verdict"], "requires_critic_review")
        hit = next(m for m in res["matches"] if m["bias_id"] == "BIAS-OVERCONFIDENCE")
        self.assertIn("mandated_correction", hit)
        self.assertIn("harness_mapping", hit)

    def test_scan_detects_oscillation_marker(self) -> None:
        res = self.guard.scan("Wait, but wait, let me reconsider this again.")
        self.assertIn("BIAS-OSCILLATION", [m["bias_id"] for m in res["matches"]])

    def test_clean_text_verdict(self) -> None:
        res = self.guard.scan("根据测试输出，函数返回 200，与预期一致。")
        self.assertEqual(res["verdict"], "clean")
        self.assertEqual(res["matches"], [])

    def test_catalog_entry_without_scope_raises(self) -> None:
        import tempfile

        bad = Path(tempfile.mkdtemp()) / "bad.yaml"
        bad.write_text("biases:\n  - id: BIAS-X\n    name: x\n    scope_conditions: ''\n    counter_examples: ok\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            BiasGuard(bad)

    def test_bias_scan_tool_via_mcp(self) -> None:
        from orchestrator.server import Orchestrator, handle_request

        orch = Orchestrator(self.repo)
        resp = handle_request(orch, {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                                     "params": {"name": "bias_scan", "arguments": {"text": "官方文档说这样就够了"}}})
        payload = json.loads(resp["result"]["content"][0]["text"])
        self.assertIn("BIAS-AUTHORITY", [m["bias_id"] for m in payload["matches"]])

    def test_dispatch_auto_scans_result(self) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.headers.get("x-harness-agent-id", "?"))
            content = "这个方案绝对没问题，肯定能过。" if len(calls) == 1 else "FAIL: overclaim"
            return sse_response(content, model="m")

        result = dispatch_subtask(
            agent_profile="coder",
            task_text="评估方案",
            gateway_url="http://mock.local",
            transport=httpx.MockTransport(handler),
            escalate_on_bias=True,
        )
        self.assertIn("BIAS-OVERCONFIDENCE", [m["bias_id"] for m in result["bias_scan"]["matches"]])
        self.assertEqual(calls, ["coder", "critic"])  # escalated to cross-family critic
        self.assertIn("FAIL", result["critic_verdict"])


class TestPlanAndRunPlan(unittest.TestCase):
    def test_plan_numbered_list_parallel(self) -> None:
        from orchestrator.plan import plan_task
        plan = plan_task("请完成三件事：1. 解析 config.yaml 的结构 2. 统计 tests/ 下测试数量 3. 列出 TODO 注释")
        self.assertEqual(len(plan["subtasks"]), 3)
        self.assertTrue(plan["parallel"])  # no sequential markers -> one wave
        self.assertEqual(plan["waves"], [["S1", "S2", "S3"]])
        for st in plan["subtasks"]:
            self.assertIn(st["agent_profile"], ("explorer", "coder", "deep", "critic"))

    def test_plan_sequential_marker_creates_chain(self) -> None:
        from orchestrator.plan import plan_task
        plan = plan_task("任务：1. 先读取日志文件找错误行 2. 然后再根据错误定位对应源码 3. 最后总结根因")
        self.assertEqual(plan["subtasks"][1]["depends_on"], ["S1"])
        self.assertEqual(len(plan["waves"]), 3)

    def test_plan_conservative_single_subtask(self) -> None:
        from orchestrator.plan import plan_task
        plan = plan_task("把 MAX_RETRY_COUNT 转成 camelCase，直接给我结果")
        self.assertEqual(len(plan["subtasks"]), 1)

    def test_run_plan_parallel_and_context_passing(self) -> None:
        from orchestrator.plan import run_plan
        import threading
        concurrent_peak = 0
        active = 0
        lock = threading.Lock()
        contexts: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal concurrent_peak, active
            with lock:
                active += 1
                concurrent_peak = max(concurrent_peak, active)
            import time; time.sleep(0.15)
            body = json.loads(request.content.decode("utf-8"))
            user = body["messages"][-1]["content"]
            sid = request.headers.get("x-harness-session-id", "?")
            contexts[sid] = user
            with lock:
                active -= 1
            return sse_response(f"result-{sid}", model="mock")

        res = run_plan(
            subtasks=[
                {"id": "A", "task_text": "分析模块A的依赖关系"},
                {"id": "B", "task_text": "分析模块B的依赖关系"},
                {"id": "C", "task_text": "合并A和B的结论给出最终方案", "depends_on": ["A", "B"], "agent_profile": "deep"},
            ],
            transport=httpx.MockTransport(handler),
            timeout=30,
        )
        self.assertGreaterEqual(concurrent_peak, 2)  # A and B truly ran in parallel
        self.assertIn("Upstream sub-agent results", contexts["C"])
        self.assertIn("result-A", contexts["C"])
        self.assertEqual(res["results"]["C"]["agent_profile"], "deep")
        self.assertEqual(set(res["bias_scan_summary"]), {"A", "B", "C"})
        self.assertIn("result-C", res["aggregate"])

    def test_run_plan_over_mcp_bridge(self) -> None:
        from orchestrator.server import Orchestrator, handle_request
        orch = Orchestrator(Path(__file__).resolve().parent.parent)
        # avoid real gateway: monkeypatch dispatch used by run_plan
        import orchestrator.plan as plan_mod
        original = plan_mod.dispatch_subtask
        plan_mod.dispatch_subagent = None
        def fake_dispatch(**kw):
            return {"agent_profile": kw["agent_profile"], "task_id": kw["task_id"], "content": "ok",
                    "routed_tier": "system_1", "selected_model": "m", "tier_tag": "t", "usage": {},
                    "bias_scan": {"matches": [], "verdict": "clean"}}
        plan_mod.dispatch_subtask = fake_dispatch
        try:
            resp = handle_request(orch, {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                                         "params": {"name": "run_plan", "arguments": {
                                             "task_text": "1. 检查版本号 2. 更新changelog"}}})
            payload = json.loads(resp["result"]["content"][0]["text"])
            self.assertEqual(len(payload["results"]), 2)
        finally:
            plan_mod.dispatch_subtask = original


class TestTooledSubAgent(unittest.TestCase):
    def _proc(self, code=0, out="done", err=""):
        import subprocess
        return subprocess.CompletedProcess(args=[], returncode=code, stdout=out, stderr=err)

    def test_builds_isolated_pi_command(self) -> None:
        from orchestrator.tooled import dispatch_tooled
        captured = {}

        def fake_run(argv, **kw):
            captured["argv"] = argv
            captured["cwd"] = kw.get("cwd")
            return self._proc()

        res = dispatch_tooled("implement parser", runner=fake_run, pi_bin="pi")
        self.assertEqual(res["status"], "ok")
        argv = captured["argv"]
        self.assertIn("-p", argv)
        self.assertIn("--no-session", argv)
        self.assertIn("--no-mcp", argv)
        self.assertIn("--no-skills", argv)
        self.assertEqual(argv[argv.index("--provider") + 1], "harness-router")
        self.assertEqual(res["workdir"], str(Path(__file__).resolve().parent.parent))

    def test_timeout_is_reported_not_raised(self) -> None:
        import subprocess
        from orchestrator.tooled import dispatch_tooled

        def boom(argv, **kw):
            raise subprocess.TimeoutExpired(cmd=argv, timeout=kw.get("timeout", 1))

        res = dispatch_tooled("slow task", runner=boom, pi_bin="pi", timeout=0.01)
        self.assertEqual(res["status"], "timeout")
        self.assertIn("exceeded", res["error"])

    def test_rejects_workdir_outside_allowed_roots(self) -> None:
        from orchestrator.tooled import dispatch_tooled
        res = dispatch_tooled("x", workdir="/", runner=lambda *a, **k: self._proc(), pi_bin="pi")
        self.assertEqual(res["status"], "rejected")

    def test_reports_missing_pi_binary(self) -> None:
        from orchestrator import tooled
        original = tooled.shutil.which
        tooled.shutil.which = lambda _: None
        try:
            res = tooled.dispatch_tooled("x", pi_bin=None)
        finally:
            tooled.shutil.which = original
        self.assertEqual(res["status"], "unavailable")
