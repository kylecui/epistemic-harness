"""Blue/green traces must merge by time and never be read from one shard only."""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.traces_tail as tail  # noqa: E402


class TraceShardTests(unittest.TestCase):
    def test_shards_are_merged_in_time_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "blue").mkdir()
            (root / "green").mkdir()
            (root / "gateway_traces.jsonl").write_text(
                json.dumps({"ts": "2026-11-26T00:00:01", "event": "legacy"}) + "\n", encoding="utf-8")
            (root / "blue" / "gateway_traces.jsonl").write_text(
                json.dumps({"ts": "2026-11-26T00:00:03", "selected_model": "b"}) + "\n", encoding="utf-8")
            (root / "green" / "gateway_traces.jsonl").write_text(
                json.dumps({"ts": "2026-11-26T00:00:02", "all_unavailable": True,
                            "event": "all_unavailable"}) + "\n", encoding="utf-8")
            with mock.patch.object(tail, "TRACES", root):
                files = tail.shard_files()
                events = tail.read_events(files)
        self.assertEqual([e["_shard"] for e in events], ["legacy", "green", "blue"])
        self.assertEqual(events[0]["event"], "legacy")

    def test_an_unparseable_line_does_not_hide_the_rest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "blue").mkdir()
            (root / "blue" / "gateway_traces.jsonl").write_text(
                "not json\n" + json.dumps({"ts": "2026-11-26T00:00:05"}) + "\n", encoding="utf-8")
            with mock.patch.object(tail, "TRACES", root):
                events = tail.read_events(tail.shard_files())
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["event"], "unparseable")


if __name__ == "__main__":
    unittest.main()
