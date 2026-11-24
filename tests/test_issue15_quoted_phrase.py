"""Issue #15: a phrase inside inline quotes is a quotation, not an ask (exit gate + gateway mirror)."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from orchestrator.exit_gate import _mask_inline_quotes as host_mask, check_underdetermination as host_check
from proxy_gateway.response_guard import _mask_inline_quotes as gw_mask, check_underdetermination as gw_check

TAIL = "\n## 证据缺口与处置\n无。"
PAIRS = ((host_check, gw_check), (host_mask, gw_mask))


def both(index: int, text: str):
    """Run the exit-gate copy and the gateway copy on the same text; they must agree."""
    a, b = PAIRS[index][0](text), PAIRS[index][1](text)
    norm = lambda v: [x.split(":")[0] for x in v] if isinstance(v, list) else v  # noqa: E731  wording differs
    assert norm(a) == norm(b), f"exit gate and gateway disagree: {a!r} vs {b!r}"
    return a


class QuotedPhraseTests(unittest.TestCase):
    def test_quoting_a_verdict_or_a_phrase_is_not_an_ask(self) -> None:
        for line in ('上一条有一处措辞被门禁判成“伪决策点”，是我写错了：那句是陈述，不是提问。',
                     '门禁说这是「伪决策点」，但那句只是在引用。',
                     'The reviewer wrote "需要你确认" in its last message; that was a quotation.',
                     "Line 34 said `由你决定何时重试` and nothing else."):
            self.assertEqual(both(0, "## 核心结论\n" + line + TAIL), [], line)

    def test_quote_wrapped_across_two_lines(self) -> None:
        text = "## 核心结论\n上一条被判成“伪\n决策点”，那是在引用。" + TAIL
        self.assertEqual(both(0, text), [])
        self.assertEqual(both(1, text).count("\n"), text.count("\n"))  # line numbers hold

    def test_unquoted_ask_without_a_layer_is_still_flagged(self) -> None:
        violations = both(0, "## 核心结论\n要不要开自动重试，由你决定。" + TAIL)
        self.assertEqual(len(violations), 1, violations)
        self.assertIn("由你决定", violations[0])

    def test_ask_with_labelled_l4_trade_off_passes(self) -> None:
        text = "## 核心结论\n要不要开自动重试，需要你决定。这是 L4 取舍：少一次手动重发，换出错时多等最长 60 秒。" + TAIL
        self.assertEqual(both(0, text), [])

    def test_unbalanced_quote_does_not_hide_a_real_ask(self) -> None:
        line = '它有 5" 长。要不要重试，由你决定。'
        violations = both(0, "## 核心结论\n" + line + TAIL)
        self.assertEqual(len(violations), 1, violations)  # fail open: the stray quote masks nothing

    def test_masking_preserves_length_and_columns(self) -> None:
        line = '被判成“伪决策点”，ABC `由你决定` 末尾'
        masked = both(1, line)
        self.assertEqual(len(masked), len(line))
        self.assertEqual(masked.index("，ABC"), line.index("，ABC"))
        self.assertNotIn("伪决策点", masked)
        self.assertNotIn("由你决定", masked)


if __name__ == "__main__":
    unittest.main()
