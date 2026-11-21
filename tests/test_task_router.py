"""Task router: data-driven category decisions, graceful degradation, dispatch params."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ.setdefault("HARNESS_TRACES_DIR", tempfile.mkdtemp(prefix="harness-test-traces-"))

import yaml

PACK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK_ROOT))

from orchestrator.task_router import (  # noqa: E402
    classify_category, route_task, validate_against_capability, as_dict,
)
from orchestrator.dispatch import dispatch_subtask  # noqa: E402

import httpx  # noqa: E402

TEST_CONFIG = {
    "categories": {
        "quick-fix": {"match": ["rename"], "decision": {"profile": "coder", "effort": "low", "budget": 2048}},
        "deep-analysis": {
            "match": ["证明"],
            "decision": {"profile": "deep", "effort": "high", "budget": 8192, "model": "zhipu-glm-5.3"},
        },
    },
    "default": {"decision": {"profile": "coder", "effort": "medium", "budget": 4096}},
}

CAPABILITY = {
    "models": [
        {"model": "zhipu-glm-5.3", "efforts_allowed": ["minimal", "low", "medium", "high"], "efforts_clamped": []},
        {"model": "m-clamped", "efforts_allowed": ["minimal", "low"], "efforts_clamped": ["medium", "high"]},
    ]
}


class RouterTests(unittest.TestCase):
    def test_category_first_hit_wins(self):
        self.assertEqual(classify_category("please rename this symbol", TEST_CONFIG), ("quick-fix", "rename"))
        self.assertEqual(classify_category("形式化证明一致性", TEST_CONFIG), ("deep-analysis", "证明"))
        self.assertEqual(classify_category("完全无关的话", TEST_CONFIG), ("default", None))

    def test_priority_beats_file_order(self):
        cfg = {
            "categories": {
                "low-p": {"priority": 1, "match": ["分析"], "decision": {"profile": "coder", "effort": "low"}},
                "high-p": {"priority": 9, "match": ["复核"], "decision": {"profile": "critic", "effort": "high"}},
            },
            "default": {"decision": {"profile": "coder", "effort": "medium"}},
        }
        # '复核' only exists in high-p; add a shared keyword case:
        cfg["categories"]["shared-a"] = {"priority": 2, "match": ["定位"], "decision": {"profile": "explorer", "effort": "low"}}
        cfg["categories"]["shared-b"] = {"priority": 8, "match": ["定位"], "decision": {"profile": "critic", "effort": "high"}}
        self.assertEqual(classify_category("帮我定位并复核问题", cfg), ("high-p", "复核"))

    def test_overlap_is_reported_as_warning(self):
        cfg = {
            "categories": {
                "a": {"match": ["x"], "decision": {"profile": "coder", "effort": "low"}},
                "b": {"match": ["x"], "decision": {"profile": "coder", "effort": "low"}},
            },
            "default": {"decision": {"profile": "coder", "effort": "medium"}},
        }
        violations = validate_against_capability(cfg, CAPABILITY)
        self.assertTrue(any(v.startswith("warning:") for v in violations))
        self.assertFalse(any(not v.startswith("warning:") for v in violations))

    def test_route_uses_table(self):
        r = route_task("rename foo", TEST_CONFIG)
        self.assertEqual((r.category, r.profile, r.effort, r.budget), ("quick-fix", "coder", "low", 2048))
        self.assertEqual(r.source, "table")

    def test_explicit_profile_and_effort_win(self):
        r = route_task("rename foo", TEST_CONFIG, explicit_profile="critic", explicit_effort="high")
        self.assertEqual((r.profile, r.effort, r.source), ("critic", "high", "explicit"))

    def test_unknown_model_pin_warns_not_fails(self):
        cfg = {"categories": {"x": {"match": ["x"], "decision": {"profile": "coder", "effort": "low",
                                                                  "model": "ghost-model"}}}}
        r = route_task("x", cfg, capability=CAPABILITY)
        self.assertIsNone(r.model)
        self.assertTrue(any("ghost-model" in w for w in r.warnings))

    def test_clamped_effort_warns(self):
        cfg = {"categories": {"x": {"match": ["x"], "decision": {"profile": "coder", "effort": "high",
                                                                  "model": "m-clamped"}}}}
        r = route_task("x", cfg, capability=CAPABILITY)
        self.assertTrue(any("钳制" in w for w in r.warnings))

    def test_validation_flags_bad_entries(self):
        bad = {
            "categories": {"a": {"match": [], "decision": {"profile": "ghost", "effort": "high",
                                                           "model": "not-a-model"}}},
            "default": {"decision": {"profile": "coder", "effort": "medium"}},
        }
        violations = validate_against_capability(bad, CAPABILITY)
        self.assertTrue(any("ghost" in v for v in violations))
        self.assertTrue(any("not-a-model" in v for v in violations))

    def test_repo_config_is_valid(self):
        from orchestrator.task_router import load_config
        from scripts.capability_matrix import build_matrix, validate_routing
        self.assertEqual(validate_routing(PACK_ROOT / "config" / "task_routing.yaml", build_matrix()), [])


class DispatchParamTests(unittest.TestCase):
    def _gateway(self, captured: dict) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content.decode("utf-8"))
            captured["headers"] = dict(request.headers)
            sse = (
                'data: {"choices":[{"delta":{"content":"ok"}}],"usage":{"prompt_tokens":1,"completion_tokens":1}}\n'
                "data: [DONE]\n"
            )
            return httpx.Response(200, headers={
                "Content-Type": "text/event-stream",
                "X-Harness-Routed-Tier": "system_2",
                "X-Harness-Selected-Model": "zhipu-glm-5.3",
                "X-Harness-Effort": "high",
            }, content=sse.encode("utf-8"))
        return httpx.MockTransport(handler)

    def test_model_and_effort_params_pass_through(self):
        captured: dict = {}
        result = dispatch_subtask(
            agent_profile="deep", task_text="x", task_id="t-param",
            model="zhipu-glm-5.3", effort="high", transport=self._gateway(captured),
        )
        self.assertEqual(captured["body"]["model"], "zhipu-glm-5.3")
        self.assertEqual(captured["headers"].get("x-harness-effort"), "high")
        self.assertEqual(result["selected_model"], "zhipu-glm-5.3")
        self.assertEqual(result["effort"], "high")

    def test_defaults_omit_pin_and_effort_header(self):
        captured: dict = {}
        dispatch_subtask(agent_profile="coder", task_text="x", task_id="t-def",
                         transport=self._gateway(captured))
        self.assertNotIn("model", captured["body"])
        self.assertNotIn("x-harness-effort", captured["headers"])


if __name__ == "__main__":
    unittest.main()
