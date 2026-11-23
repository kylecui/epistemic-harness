"""Regression tests for the 2026-11-24 harness issue fixes (#6, #10, #11)."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proxy_gateway.response_guard import (  # noqa: E402
    check_output_structure,
    normalize_declared_cap,
    weakest_body_layer,
)


class CapExcludesIntentLayerTests(unittest.TestCase):
    """#10: L4 (intent) and L5 (derivation marker) are not confidence inputs."""

    def test_weakest_layer_ignores_l4_and_l5(self):
        self.assertEqual(weakest_body_layer("[L2] measured [L4] user goal [L5] derived"), 2)

    def test_weakest_layer_still_sees_l3(self):
        self.assertEqual(weakest_body_layer("[L2] fact [L3] rule of thumb"), 3)

    def test_header_not_dragged_to_l4_by_goal_mention(self):
        text = "[Tier: x | Mode: Converge | Confidence Cap: L2]\n\n[L2] evidence line\n\n[L4] user wants it fast"
        _, note = normalize_declared_cap(text)
        self.assertIsNone(note)


class LowTierLightOutputTests(unittest.TestCase):
    """#6: Tier 0/1 keep the light output contract in Converge mode too."""

    LONG = "x" * 1500 + " [L2] evidence"

    def test_tier1_converge_does_not_require_section_anchors(self):
        violations = check_output_structure(LONG, "system_1", "Converge")
        self.assertFalse(any("三段式锚点" in v for v in violations), violations)

    def test_tier15_still_requires_section_anchors(self):
        violations = check_output_structure(LONG, "system_1_5", "Explore")
        self.assertTrue(any("三段式锚点" in v for v in violations), violations)


class BadgeAutoSyncTests(unittest.TestCase):
    """#11: check_docs rewrites the badge instead of failing."""

    def test_badge_is_rewritten_to_discovered_count(self):
        spec = importlib.util.spec_from_file_location("check_docs_sync", REPO_ROOT / "scripts" / "check_docs.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "README.md").write_text("# t\n\nbadge tests-1%20green ok\n", encoding="utf-8")
            (Path(tmp) / "README_ZH.md").write_text("badge tests-1%20green ok\n", encoding="utf-8")
            orig_root, orig_count = mod.REPO_ROOT, mod._discover_test_count
            mod.REPO_ROOT = Path(tmp)
            mod._discover_test_count = lambda: 7
            try:
                problems: list[str] = []
                mod.check_test_count_badge(problems)
            finally:
                mod.REPO_ROOT, mod._discover_test_count = orig_root, orig_count
            self.assertEqual(problems, [])
            self.assertIn("tests-7%20green", (Path(tmp) / "README.md").read_text(encoding="utf-8"))
            self.assertIn("tests-7%20green", (Path(tmp) / "README_ZH.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
