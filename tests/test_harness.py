from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from backtester.broker import LocalSimBroker
from backtester.events import QuoteEvent, RawEvent, SignalEvent, TradeEvent
from backtester.harness import HarnessConfig, Mode, ReplayHarness
from backtester.source import IterableEventSource
from backtester.strategy import Context, Order, OrderSide, Strategy


def _ts(s: int) -> datetime:
    return datetime(2026, 4, 12, tzinfo=timezone.utc) + timedelta(seconds=s)


class BuyAndHold(Strategy):
    def __init__(self, symbol: str, qty: float = 10) -> None:
        self.symbol = symbol
        self.qty = qty
        self._sent = False
        self.fills_seen = 0

    def on_event(self, event: RawEvent, ctx: Context) -> None:
        if not self._sent and isinstance(event, QuoteEvent) and event.symbol == self.symbol:
            ctx.broker.submit(Order(symbol=self.symbol, side=OrderSide.BUY, qty=self.qty))
            self._sent = True

    def on_fill(self, fill, ctx: Context) -> None:
        self.fills_seen += 1


class SignalReactive(Strategy):
    """Reacts to both market + signal events — verifies polymorphic dispatch."""

    def __init__(self) -> None:
        self.signals: list[SignalEvent] = []
        self.market: list[RawEvent] = []

    def on_event(self, event: RawEvent, ctx: Context) -> None:
        if isinstance(event, SignalEvent):
            self.signals.append(event)
        else:
            self.market.append(event)


class HarnessIntegrationTests(unittest.TestCase):
    def test_buy_and_hold_produces_positive_pnl_on_uptrend(self) -> None:
        events = [
            QuoteEvent(ts=_ts(0), symbol="SPY", bid=100.0, ask=100.1),
            QuoteEvent(ts=_ts(1), symbol="SPY", bid=101.0, ask=101.1),
            QuoteEvent(ts=_ts(2), symbol="SPY", bid=105.0, ask=105.1),
        ]
        harness = ReplayHarness(
            source=IterableEventSource(events),
            strategy=BuyAndHold("SPY"),
            broker=LocalSimBroker(),
            config=HarnessConfig(starting_cash=10_000.0, mode=Mode.HISTORICAL),
        )
        report = harness.run()
        self.assertGreater(report.ending_equity, 10_000.0)
        self.assertEqual(report.trades.total_fills, 1)

    def test_deterministic_two_runs(self) -> None:
        events = [
            QuoteEvent(ts=_ts(0), symbol="SPY", bid=100.0, ask=100.1),
            QuoteEvent(ts=_ts(1), symbol="SPY", bid=101.0, ask=101.1),
        ]
        r1 = ReplayHarness(
            source=IterableEventSource(list(events)),
            strategy=BuyAndHold("SPY"),
        ).run()
        r2 = ReplayHarness(
            source=IterableEventSource(list(events)),
            strategy=BuyAndHold("SPY"),
        ).run()
        self.assertEqual(r1.ending_equity, r2.ending_equity)
        self.assertEqual(r1.equity_curve, r2.equity_curve)

    def test_polymorphic_events_all_reach_strategy(self) -> None:
        events = [
            QuoteEvent(ts=_ts(0), symbol="SPY", bid=100.0, ask=100.1),
            SignalEvent(ts=_ts(1), symbol="SPY", name="sentiment", value=0.5),
            TradeEvent(ts=_ts(2), symbol="SPY", price=100.5, size=10),
        ]
        strategy = SignalReactive()
        ReplayHarness(
            source=IterableEventSource(events),
            strategy=strategy,
        ).run()
        self.assertEqual(len(strategy.signals), 1)
        self.assertEqual(len(strategy.market), 2)

    def test_clock_moves_monotonically(self) -> None:
        events = [
            QuoteEvent(ts=_ts(1), symbol="SPY", bid=100.0, ask=100.1),
            QuoteEvent(ts=_ts(0), symbol="SPY", bid=100.0, ask=100.1),
        ]
        with self.assertRaises(ValueError):
            ReplayHarness(
                source=IterableEventSource(events),
                strategy=BuyAndHold("SPY"),
            ).run()


if __name__ == "__main__":
    unittest.main()
