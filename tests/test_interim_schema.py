"""Structured interim output guards: schema subset validator + SubagentReport wrapper."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestrator.subagent_report import build_report, validate_report
from proxy_gateway.interim_schema import load_schema, validate


class ValidatorSubsetTests(unittest.TestCase):
    def test_valid_report_passes(self):
        report = build_report("t-1", "coder", "first finding\n\nsecond finding")
        self.assertEqual(validate_report(report), [])

    def test_missing_required_field_flagged(self):
        report = build_report("t-1", "coder", "x")
        del report["confidence_cap"]
        violations = validate_report(report)
        self.assertTrue(any("confidence_cap" in v for v in violations))

    def test_wrong_enum_flagged(self):
        report = build_report("t-1", "coder", "x")
        report["findings"][0]["layer"] = "L9"
        violations = validate_report(report)
        self.assertTrue(any("enum" in v and "layer" in v for v in violations))

    def test_wrong_type_flagged_without_cascade(self):
        violations = validate(load_schema("subagent-report.schema.json"), {"findings": "not-a-list"})
        self.assertTrue(any("findings" in v and "type" in v for v in violations))

    def test_min_items_enforced(self):
        report = build_report("t-1", "coder", "")
        report["findings"] = []
        violations = validate_report(report)
        self.assertTrue(any("minItems" in v for v in violations))


class SubagentReportTests(unittest.TestCase):
    def test_paragraphs_become_l3_findings(self):
        report = build_report("t-2", "explorer", "alpha\n\nbeta")
        self.assertEqual([f["text"] for f in report["findings"]], ["alpha", "beta"])
        self.assertTrue(all(f["layer"] == "L3" for f in report["findings"]))
        self.assertEqual(report["confidence_cap"], "L3")

    def test_empty_result_still_valid(self):
        report = build_report("t-3", "deep", "")
        self.assertEqual(validate_report(report), [])

    def test_unknown_profile_falls_back(self):
        report = build_report("t-4", "nonsense", "x")
        self.assertEqual(report["profile"], "explorer")

    def test_readonly_profile_is_kept(self):
        report = build_report("ro-1", "explorer-ro", "listed 3 files")
        self.assertEqual(report["profile"], "explorer-ro")
        self.assertEqual(validate_report(report), [])


if __name__ == "__main__":
    unittest.main()
