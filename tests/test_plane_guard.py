"""A file-touching dispatch that does not name its plane is a failure, not a result (#7)."""
from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orchestrator.plane_guard import require_plane  # noqa: E402


class PlaneGuardTests(unittest.TestCase):
    def test_a_declared_plane_passes_through_untouched(self) -> None:
        result = {"ok": True, "content": "x", "runner": "host", "via": "host_dispatch"}
        self.assertIs(require_plane("dispatch_readonly", result), result)

    def test_an_undeclared_plane_is_refused_with_a_remedy(self) -> None:
        out = require_plane("dispatch_tooled", {"ok": True, "content": "x", "runner": None})
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "plane_undeclared")
        self.assertIn("runner=host|container", out["message"])

    def test_a_missing_key_or_a_bogus_value_is_refused(self) -> None:
        self.assertEqual(require_plane("dispatch_readonly", {"ok": True})["error"], "plane_undeclared")
        self.assertEqual(require_plane("dispatch_readonly", {"runner": "somewhere"})["error"],
                         "plane_undeclared")

    def test_text_only_dispatch_needs_no_plane(self) -> None:
        result = {"ok": True, "content": "x"}
        self.assertIs(require_plane("dispatch_subagent", result), result)


if __name__ == "__main__":
    unittest.main()
