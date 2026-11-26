"""Issue #26: a text-only controller must be able to delegate looking at an image — or be told no."""
from __future__ import annotations

import base64
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import orchestrator.vision as vision  # noqa: E402

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFElEQVR4nGP8z8Dwn4GBgYGRgQEAGrIC/6d9kS0AAAAASUVORK5CYII=")


class CapabilityTests(unittest.TestCase):
    def test_only_declared_vision_models_are_chosen(self) -> None:
        catalog = {"text-only": {"vision": False}, "eyes": {"vision": True}}
        self.assertEqual(vision.vision_model_for(catalog), "eyes")
        self.assertEqual(vision.vision_model_for(catalog, "eyes"), "eyes")
        self.assertEqual(vision.vision_model_for(catalog, "text-only"), "eyes", "a request for a blind model falls to a capable one")

    def test_no_vision_model_is_an_error_not_a_text_answer(self) -> None:
        catalog = {"text-only": {"vision": False}}
        self.assertIsNone(vision.vision_model_for(catalog))
        out = vision.analyze_image("what is this?", ["x.png"], catalog=catalog)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "no_vision_model")


class AttachmentTests(unittest.TestCase):
    def test_an_image_becomes_one_data_url_block_after_the_question(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "shot.png"
            path.write_bytes(PNG)
            mime, b64 = vision.read_image(path)
        blocks = vision.build_content("what colour?", [(mime, b64)])
        self.assertEqual(blocks[0]["type"], "text")
        self.assertTrue(blocks[1]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_a_missing_or_unsupported_file_is_named(self) -> None:
        with self.assertRaises(ValueError) as missing:
            vision.read_image("/nonexistent/shot.png")
        self.assertIn("not found", str(missing.exception))
        with tempfile.TemporaryDirectory() as tmp:
            bad = pathlib.Path(tmp) / "notes.txt"
            bad.write_text("x", encoding="utf-8")
            with self.assertRaises(ValueError) as unsupported:
                vision.read_image(bad)
        self.assertIn("unsupported", str(unsupported.exception))

    def test_the_gateway_is_told_not_to_wrap_the_answer_in_the_contract(self) -> None:
        captured: dict = {}

        class FakeResp:
            headers = {"x-harness-selected-model": "eyes"}

            def read(self) -> bytes:
                return b'{"choices":[{"message":{"content":"Red"}}]}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=0):  # noqa: ANN001, ANN202
            captured["headers"] = dict(req.headers)
            captured["body"] = req.data
            return FakeResp()

        with tempfile.TemporaryDirectory() as tmp:
            shot = pathlib.Path(tmp) / "shot.png"
            shot.write_bytes(PNG)
            with mock.patch.object(vision.urllib.request, "urlopen", fake_urlopen):
                out = vision.analyze_image("colour?", [str(shot)], catalog={"eyes": {"vision": True}})
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["model"], "eyes")
        self.assertEqual(out["answer"], "Red")
        self.assertIn("X-Harness-No-Contract".lower(), {k.lower() for k in captured["headers"]})


if __name__ == "__main__":
    unittest.main()
