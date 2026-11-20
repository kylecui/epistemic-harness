"""Unit tests verifying anti-jargon, anti-translationese, and A/B golden test scoring."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import sys
import unittest
import yaml

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
YAML_PATH = BUNDLE_ROOT / "evals" / "golden_cases_style_ab.yaml"
RUNNER_PATH = BUNDLE_ROOT / "evals" / "run_style_ab_eval.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_style_ab_eval", RUNNER_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["run_style_ab_eval"] = mod
    spec.loader.exec_module(mod)
    return mod


class TestStyleAndGoldenAB(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = _load_runner()
        cls.spec = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
        cls.style_rules = cls.spec["style_rules"]
        cls.cases = {c["id"]: c for c in cls.spec["cases"]}

    def test_treatment_passes_all_new_golden_cases_with_zero_jargon(self):
        for cid in ("TC-07", "TC-08", "TC-09"):
            entry = self.runner.REPLAY_TRANSCRIPTS["treatment_en_agents_md"][cid]
            score = self.runner.score_response(
                self.cases[cid],
                self.style_rules,
                "treatment_en_agents_md",
                entry["reply"],
                entry["thoughts"],
            )
            self.assertTrue(score.passed, f"{cid} treatment failed: {score}")
            self.assertEqual(score.thought_lang, "EN")
            self.assertEqual(score.zh_buzzwords, [])
            self.assertEqual(score.en_slop_hits, [])
            self.assertEqual(score.translationese_hits, [])

    def test_control_tc07_exposes_language_drift_and_buzzword_leakage(self):
        entry = self.runner.REPLAY_TRANSCRIPTS["control_zh_skill"]["TC-07"]
        score = self.runner.score_response(
            self.cases["TC-07"],
            self.style_rules,
            "control_zh_skill",
            entry["reply"],
            entry["thoughts"],
        )
        self.assertFalse(score.passed)
        self.assertEqual(score.thought_lang, "ZH")
        self.assertIn("降本增效", score.zh_buzzwords)
        self.assertIn("打通", score.zh_buzzwords)

    def test_negative_control_catches_en_slop_and_translationese(self):
        bad_thoughts = "We should leverage a holistic paradigm to seamlessly streamline this robust plan."
        bad_reply = "我们需要围绕底层逻辑打造核心抓手，形成赋能闭环。这是一个被外部专家所强力推荐的方案。"
        score = self.runner.score_response(
            self.cases["TC-07"],
            self.style_rules,
            "negative_control",
            bad_reply,
            bad_thoughts,
        )
        self.assertFalse(score.passed)
        self.assertGreaterEqual(len(score.zh_buzzwords), 4)
        self.assertGreaterEqual(len(score.en_slop_hits), 4)
        self.assertGreaterEqual(len(score.translationese_hits), 1)

    def test_agents_md_patch_contains_english_reasoning_and_anti_jargon_rules(self):
        agents_text = (BUNDLE_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Reasoning Style (English)", agents_text)
        self.assertIn("Output Style (User Language)", agents_text)
        self.assertIn("赋能", agents_text)
        self.assertIn("leverage", agents_text)


if __name__ == "__main__":
    unittest.main()


class TestQuotedBuzzwordExemption(unittest.TestCase):
    def test_quoted_occurrence_is_exempt_unquoted_is_not(self):
        from evals.run_style_ab_eval import find_unquoted
        self.assertEqual(find_unquoted("建议「打通」会员，但没有 L2 证据", ["打通"]), [])
        self.assertEqual(find_unquoted('他说"打通"后失败', ["打通"]), [])
        self.assertEqual(find_unquoted("建议打通会员", ["打通"]), ["打通"])
        self.assertEqual(find_unquoted('他说「打通」；后来又提"打通"；最终仍主张打通', ["打通"]), ["打通"])
