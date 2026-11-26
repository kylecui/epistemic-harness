"""A sub-agent report is machine input: no three-section anchors, but content checks stay (#27)."""
from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from proxy_gateway.response_guard import check_output_structure, check_response_contract  # noqa: E402

PLAIN = ("The trace shows a stale copy of the contract. The script reads the repo file, not the live "
         "session. Fix: rerun the installer, then restart the client so the compiled contract loads. ") * 4
SUPERLATIVE = PLAIN + "This is the SOTA approach for memory retrieval."


class DispatchContractTests(unittest.TestCase):
    def test_a_user_turn_still_needs_the_anchors(self) -> None:
        violations = check_output_structure(PLAIN, "system_1_5", "converge")
        self.assertTrue([v for v in violations if "三段式" in v], violations[:3])

    def test_a_dispatch_report_is_not_judged_on_anchors(self) -> None:
        violations = check_output_structure(PLAIN, "system_1_5", "converge", dispatch=True)
        self.assertFalse([v for v in violations if "三段式" in v], violations[:3])

    def test_a_dispatch_report_is_still_judged_on_content(self) -> None:
        violations = check_response_contract(SUPERLATIVE, "system_2", "converge", dispatch=True)
        self.assertTrue(violations, "an unanchored superlative is content, not formatting")
        user_side = check_response_contract(SUPERLATIVE, "system_2", "converge")
        self.assertGreaterEqual(len(user_side), len(violations))


if __name__ == "__main__":
    unittest.main()
