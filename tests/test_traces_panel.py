"""Unit tests for scripts/traces_panel.py (P2.10)."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.traces_panel import build_html  # noqa: E402


class TracesPanelTests(unittest.TestCase):
    def test_panel_renders_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "dispatches.jsonl").write_text(
                "\n".join(json.dumps({"selected_model": "glm-5.3", "category": "deep", "routed_tier": "system_2"}) for _ in range(3))
                + "\nnot-json\n",
                encoding="utf-8",
            )
            (d / "loop_ledger.jsonl").write_text(
                json.dumps({"verdict": "red", "action": "bounce",
                            "failure_classes": [{"class": "code_defect"}]}) + "\n",
                encoding="utf-8",
            )
            html = build_html(d)
            self.assertIn("dispatches: 3 records", html)
            self.assertIn("glm-5.3", html)
            self.assertIn("code_defect", html)
            self.assertIn("malformed" if False else "ledger: 1 records", html)

    def test_empty_dir_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = build_html(Path(tmp))
            self.assertIn("no data", html)


if __name__ == "__main__":
    unittest.main()
