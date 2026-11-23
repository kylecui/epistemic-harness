"""Public-language gate unit tests (CJK detection + explicit-zh marker)."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "check_public_language_under_test", REPO_ROOT / "scripts" / "check_public_language.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cpl = _load()


class CjkDetectionTests(unittest.TestCase):
    def test_detects_han_hiragana_hangul(self):
        self.assertTrue(cpl.has_cjk("修复 bash 工具"))
        self.assertTrue(cpl.has_cjk("テスト"))
        self.assertTrue(cpl.has_cjk("테스트"))

    def test_pure_ascii_is_clean(self):
        self.assertFalse(cpl.has_cjk("fix gateway payload"))
        self.assertFalse(cpl.has_cjk("v0.5.2: align planes"))


class MarkerTests(unittest.TestCase):
    def test_marker_explicitly_allows_chinese(self):
        self.assertTrue(cpl.message_declared_zh("修复说明 [zh]"))
        self.assertTrue(cpl.message_declared_zh("Lang: zh 修复说明"))
        self.assertFalse(cpl.message_declared_zh("修复说明"))
        self.assertFalse(cpl.message_declared_zh("align planes"))


if __name__ == "__main__":
    unittest.main()
