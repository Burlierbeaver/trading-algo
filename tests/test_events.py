from __future__ import annotations

import unittest
from datetime import datetime, timezone

from backtester.events import (
    BarEvent,
    NewsEvent,
    QuoteEvent,
    SignalEvent,
    TradeEvent,
    from_dict,
    parse_ts,
)


class EventConstructionTests(unittest.TestCase):
    def test_quote_mid(self) -> None:
        ts = datetime(2026, 4, 12, tzinfo=timezone.utc)
        q = QuoteEvent(ts=ts, symbol="SPY", bid=100.0, ask=100.2, bid_size=10, ask_size=12)
        self.assertAlmostEqual(q.mid, 100.1)

    def test_naive_ts_rejected(self) -> None:
        with self.assertRaises(ValueError):
            TradeEvent(ts=datetime(2026, 4, 12), symbol="SPY", price=1.0, size=1.0)

    def test_from_dict_quote(self) -> None:
        ev = from_dict(
            {
                "type": "quote",
                "ts": "2026-04-12T00:00:00Z",
                "symbol": "AAPL",
                "bid": 170.0,
                "ask": 170.1,
                "bid_size": 100,
                "ask_size": 100,
            }
        )
        self.assertIsInstance(ev, QuoteEvent)
        self.assertEqual(ev.symbol, "AAPL")

    def test_from_dict_signal_null_payload(self) -> None:
        ev = from_dict(
            {
                "type": "signal",
                "ts": 1_700_000_000,
                "symbol": "AAPL",
                "name": "sentiment",
                "value": 0.8,
                "confidence": 0.7,
                "payload": None,
            }
        )
        self.assertIsInstance(ev, SignalEvent)
        self.assertEqual(dict(ev.payload), {})

    def test_from_dict_unknown_type(self) -> None:
        with self.assertRaises(ValueError):
            from_dict({"type": "oops", "ts": "2026-04-12T00:00:00Z"})

    def test_parse_ts_handles_epoch_and_iso(self) -> None:
        epoch_ts = parse_ts(1_700_000_000)
        iso_ts = parse_ts("2026-04-12T00:00:00Z")
        self.assertIsNotNone(epoch_ts.tzinfo)
        self.assertIsNotNone(iso_ts.tzinfo)

    def test_news_and_bar_roundtrip(self) -> None:
        bar = from_dict(
            {
                "type": "bar",
                "ts": "2026-04-12T00:00:00Z",
                "symbol": "SPY",
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 1000,
            }
        )
        news = from_dict(
            {
                "type": "news",
                "ts": "2026-04-12T00:00:00Z",
                "headline": "hello",
                "body": "",
                "source": "rss",
                "url": "",
                "tags": [],
            }
        )
        self.assertIsInstance(bar, BarEvent)
        self.assertIsInstance(news, NewsEvent)


if __name__ == "__main__":
    unittest.main()
