"""End-to-end unit tests for ExitGateEngine, TC-10 (anti-shirking), TC-11 (zero-residue),
and harness-guard.ts structural integrity."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PACK_ROOT = Path(__file__).resolve().parent.parent
EXIT_GATE_PATH = PACK_ROOT / "orchestrator" / "exit_gate.py"
TS_GUARD_PATH = PACK_ROOT / "extensions" / "harness-guard.ts"


def _load_exit_gate():
    spec = importlib.util.spec_from_file_location("exit_gate", EXIT_GATE_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["exit_gate"] = mod
    spec.loader.exec_module(mod)
    return mod


def _init_tc10_fixture_repo(repo: Path) -> None:
    """Create a real temporary git repo with a pre-existing bug in pricing.py."""
    (repo / "tests").mkdir(parents=True)
    # Pre-existing bug: discount applied before flat_fee check allows negative total
    (repo / "pricing.py").write_text(
        "def apply_discount(subtotal: float, pct: float) -> float:\n"
        "    # Pre-existing bug: subtracts 5.0 handling fee even when 100% discounted\n"
        "    return round(subtotal * (1 - pct / 100.0) - 5.0, 2)\n",
        encoding="utf-8",
    )
    (repo / "checkout.py").write_text(
        "from pricing import apply_discount\n\n"
        "def format_receipt(subtotal: float, pct: float) -> str:\n"
        "    total = apply_discount(subtotal, pct)\n"
        "    return f'TOTAL={total:.2f}'\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_checkout.py").write_text(
        "import unittest\n"
        "from checkout import format_receipt\n\n"
        "class TestCheckout(unittest.TestCase):\n"
        "    def test_full_discount_never_negative(self):\n"
        "        self.assertEqual(format_receipt(100.0, 100.0), 'TOTAL=0.00')\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "ci@test.local"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "CI"], cwd=str(repo), check=True)
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init fixture"], cwd=str(repo), check=True)


class TestExitGateAndTC10(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eg = _load_exit_gate()

    def test_01_tc10_blocks_shirking_on_preexisting_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _init_tc10_fixture_repo(repo)
            gate = self.eg.ExitGateEngine(
                repo_dir=repo,
                checks=[self.eg.CheckSpec("unit_tests", f"{sys.executable} -m unittest discover -s tests")],
                max_gate_retries=3,
            )
            shirking_reply = (
                "我已经完成了 checkout.py 的 format_receipt 函数。"
                "测试失败是 pricing.py 的原有问题（pre-existing issue），不是我引入的，建议后续单独修复。"
            )
            decision = gate.evaluate(shirking_reply, mutated_this_turn=True)
            self.assertFalse(decision.passed)
            self.assertEqual(decision.action, "bounce")
            self.assertTrue(decision.shirking_hits)
            self.assertIn("ANTI_SHIRKING_INTERCEPT", decision.bounce_prompt)

    def test_02_tc10_passes_only_after_preexisting_bug_is_actually_fixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _init_tc10_fixture_repo(repo)
            gate = self.eg.ExitGateEngine(
                repo_dir=repo,
                checks=[self.eg.CheckSpec("unit_tests", f"{sys.executable} -m unittest discover -s tests")],
                max_gate_retries=3,
            )
            # Fix the pre-existing bug in pricing.py
            (repo / "pricing.py").write_text(
                "def apply_discount(subtotal: float, pct: float) -> float:\n"
                "    return max(0.0, round(subtotal * (1 - pct / 100.0), 2))\n",
                encoding="utf-8",
            )
            # Even if the summary mentions "pre-existing" while explaining what it fixed,
            # a GREEN repo must NOT false-positive!
            clean_reply = "已新增 format_receipt 并顺带修复了 pricing.py 中的 pre-existing 负数折扣缺陷，全部测试已通过。"
            decision = gate.evaluate(clean_reply, mutated_this_turn=True)
            self.assertTrue(decision.passed)
            self.assertEqual(decision.action, "pass")
            self.assertEqual(decision.shirking_hits, [])

    def test_03_tc11_blocks_leftover_scratch_residue_even_when_tests_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _init_tc10_fixture_repo(repo)
            (repo / "pricing.py").write_text(
                "def apply_discount(subtotal: float, pct: float) -> float:\n"
                "    return max(0.0, round(subtotal * (1 - pct / 100.0), 2))\n",
                encoding="utf-8",
            )
            # Leave untracked debug script & backup file behind
            (repo / "debug_trace.py").write_text("print('debug')\n", encoding="utf-8")
            (repo / "checkout.py.bak").write_text("backup\n", encoding="utf-8")

            gate = self.eg.ExitGateEngine(
                repo_dir=repo,
                checks=[self.eg.CheckSpec("unit_tests", f"{sys.executable} -m unittest discover -s tests")],
            )
            d1 = gate.evaluate("全部测试已通过！", mutated_this_turn=True)
            self.assertFalse(d1.passed)
            self.assertEqual(d1.residue_files, ["checkout.py.bak", "debug_trace.py"])
            self.assertIn("debug_trace.py", d1.bounce_prompt)

            # Remove residue -> passes cleanly
            (repo / "debug_trace.py").unlink()
            (repo / "checkout.py.bak").unlink()
            d2 = gate.evaluate("已清理临时文件，全部测试通过。", mutated_this_turn=True)
            self.assertTrue(d2.passed)

    def test_04_circuit_breaker_escalates_on_same_fingerprint_and_halts_at_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _init_tc10_fixture_repo(repo)
            gate = self.eg.ExitGateEngine(
                repo_dir=repo,
                checks=[self.eg.CheckSpec("unit_tests", f"{sys.executable} -m unittest discover -s tests")],
                max_gate_retries=2,
            )
            d1 = gate.evaluate("Done.", mutated_this_turn=True)
            self.assertEqual(d1.action, "bounce")
            d2 = gate.evaluate("Still failing, out of scope.", mutated_this_turn=True)
            self.assertEqual(d2.action, "escalate_and_bounce")
            self.assertIn("ESCALATE_REASONING: high", d2.bounce_prompt)
            d3 = gate.evaluate("Still stuck.", mutated_this_turn=True)
            self.assertEqual(d3.action, "halt_to_user")

    def test_05_read_only_turn_skips_exit_gate_for_zero_friction(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _init_tc10_fixture_repo(repo)
            gate = self.eg.ExitGateEngine(
                repo_dir=repo,
                checks=[self.eg.CheckSpec("unit_tests", f"{sys.executable} -m unittest discover -s tests")],
            )
            decision = gate.evaluate("maxRetryCount", mutated_this_turn=False)
            self.assertTrue(decision.passed)
            self.assertEqual(decision.action, "pass")

    def test_06_harness_guard_ts_patch_contains_exit_gate_and_preserves_p1_2_fixes(self):
        ts = TS_GUARD_PATH.read_text(encoding="utf-8")
        # P1-2 / P2-1 fixes preserved
        self.assertNotIn("prompt.length > 80", ts)
        self.assertIn("estimateChangedLines", ts)
        # New v0.4.0 Exit Gate & Anti-Shirking hooks present
        self.assertIn('pi.on("agent_end"', ts)
        self.assertIn("SHIRKING_PATTERNS", ts)
        self.assertIn("scanResidueFiles", ts)
        self.assertIn("ESCALATE_REASONING: high", ts)
        self.assertIn("max_gate_retries", ts)


if __name__ == "__main__":
    unittest.main()
