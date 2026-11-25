"""Guard coverage contracts (#19, #16): the extension must see codemode writes and tell the truth."""
from __future__ import annotations

import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parent.parent / "extensions" / "harness-guard.ts"


class GuardSourceContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = GUARD.read_text(encoding="utf-8")

    def test_codemode_writes_are_inspected(self) -> None:
        # #19: the write/edit branch never ran for a script that calls tools.write.
        self.assertIn("scanCodemodeWrites", self.source)
        self.assertIn("tools\\.(?:write|edit)", self.source)
        self.assertIn("literalLines > 40", self.source)

    def test_a_computed_payload_is_declared_not_ignored(self) -> None:
        self.assertIn("computed", self.source)
        self.assertIn("size cannot be checked", self.source)

    def test_the_suggestion_depends_on_what_the_session_has(self) -> None:
        # #16: the old text named orchestrator tools unconditionally.
        self.assertIn("orchestratorToolsAvailable", self.source)
        self.assertIn("no planning tool is connected in this session", self.source)
        self.assertNotIn(
            "`Large ${name} detected (${lines} lines). Run orchestrator.plan_task or dispatch_subagent(profile='critic') `",
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
