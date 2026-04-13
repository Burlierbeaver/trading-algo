from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from backtester.broker import FillConfig, LocalSimBroker
from backtester.events import QuoteEvent, TradeEvent
from backtester.strategy import Order, OrderSide, OrderType, TimeInForce


def _ts(offset_s: int = 0) -> datetime:
    return datetime(2026, 4, 12, tzinfo=timezone.utc) + timedelta(seconds=offset_s)


class BrokerTests(unittest.TestCase):
    def test_market_order_fills_at_ask(self) -> None:
        broker = LocalSimBroker()
        broker.submit(Order(symbol="SPY", side=OrderSide.BUY, qty=1, type=OrderType.MARKET))
        fills = broker.on_market_event(
            QuoteEvent(ts=_ts(), symbol="SPY", bid=99.9, ask=100.1)
        )
        self.assertEqual(len(fills), 1)
        self.assertAlmostEqual(fills[0].price, 100.1)

    def test_market_order_applies_slippage(self) -> None:
        broker = LocalSimBroker(config=FillConfig(slippage_bps=10))
        broker.submit(Order(symbol="SPY", side=OrderSide.BUY, qty=1))
        fills = broker.on_market_event(QuoteEvent(ts=_ts(), symbol="SPY", bid=100.0, ask=100.0))
        self.assertAlmostEqual(fills[0].price, 100.0 * (1 + 10 / 10_000))

    def test_limit_order_waits_for_cross(self) -> None:
        broker = LocalSimBroker()
        broker.submit(
            Order(
                symbol="SPY",
                side=OrderSide.BUY,
                qty=1,
                type=OrderType.LIMIT,
                limit_price=99.5,
                tif=TimeInForce.GTC,
            )
        )
        fills1 = broker.on_market_event(QuoteEvent(ts=_ts(), symbol="SPY", bid=99.9, ask=100.1))
        self.assertEqual(fills1, [])
        fills2 = broker.on_market_event(QuoteEvent(ts=_ts(1), symbol="SPY", bid=99.3, ask=99.4))
        self.assertEqual(len(fills2), 1)
        self.assertLessEqual(fills2[0].price, 99.5)

    def test_ioc_cancels_when_unmatched(self) -> None:
        broker = LocalSimBroker()
        broker.submit(
            Order(
                symbol="SPY",
                side=OrderSide.BUY,
                qty=1,
                type=OrderType.LIMIT,
                limit_price=50.0,
                tif=TimeInForce.IOC,
            )
        )
        broker.on_market_event(QuoteEvent(ts=_ts(), symbol="SPY", bid=99.9, ask=100.1))
        self.assertEqual(broker.open_orders(), [])

    def test_latency_delays_activation(self) -> None:
        broker = LocalSimBroker(config=FillConfig(latency_events=2))
        broker.submit(Order(symbol="SPY", side=OrderSide.BUY, qty=1))
        self.assertEqual(broker.on_market_event(TradeEvent(ts=_ts(), symbol="SPY", price=100.0, size=1)), [])
        self.assertEqual(broker.on_market_event(TradeEvent(ts=_ts(1), symbol="SPY", price=100.0, size=1)), [])
        fills = broker.on_market_event(TradeEvent(ts=_ts(2), symbol="SPY", price=100.0, size=1))
        self.assertEqual(len(fills), 1)

    def test_cancel(self) -> None:
        broker = LocalSimBroker()
        order = Order(symbol="SPY", side=OrderSide.BUY, qty=1)
        broker.submit(order)
        self.assertTrue(broker.cancel(order.id))
        self.assertEqual(broker.open_orders(), [])

    def test_symbol_scoping(self) -> None:
        broker = LocalSimBroker()
        broker.submit(Order(symbol="AAPL", side=OrderSide.BUY, qty=1))
        fills = broker.on_market_event(QuoteEvent(ts=_ts(), symbol="SPY", bid=100, ask=101))
        self.assertEqual(fills, [])
        self.assertEqual(len(broker.open_orders()), 1)


if __name__ == "__main__":
    unittest.main()
