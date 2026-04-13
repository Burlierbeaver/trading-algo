from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backtester.events import QuoteEvent, SignalEvent
from backtester.source import FileEventSource


class FileSourceTests(unittest.TestCase):
    def test_reads_jsonl(self) -> None:
        rows = [
            {"type": "quote", "ts": "2026-04-12T00:00:00Z", "symbol": "SPY", "bid": 100, "ask": 101},
            {"type": "signal", "ts": "2026-04-12T00:00:01Z", "symbol": "SPY", "name": "x", "value": 1.0},
        ]
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "events.jsonl"
            path.write_text("\n".join(json.dumps(r) for r in rows))
            events = list(FileEventSource(path))
        self.assertEqual(len(events), 2)
        self.assertIsInstance(events[0], QuoteEvent)
        self.assertIsInstance(events[1], SignalEvent)

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            FileEventSource(Path("/definitely/not/here.jsonl"))

    def test_invalid_json_reports_line(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "bad.jsonl"
            path.write_text('{"type":"quote"\n')
            with self.assertRaises(ValueError):
                list(FileEventSource(path))


if __name__ == "__main__":
    unittest.main()
