from __future__ import annotations

import unittest
from datetime import datetime, timezone

from backtester.portfolio import Fill, Portfolio
from backtester.strategy import OrderSide


def _fill(side: OrderSide, qty: float, price: float, symbol: str = "SPY") -> Fill:
    return Fill(
        order_id="x",
        symbol=symbol,
        side=side,
        qty=qty,
        price=price,
        ts=datetime(2026, 4, 12, tzinfo=timezone.utc),
    )


class PortfolioTests(unittest.TestCase):
    def test_buy_then_sell_realizes_pnl(self) -> None:
        p = Portfolio(cash=10_000.0)
        p.apply_fill(_fill(OrderSide.BUY, 10, 100.0))
        p.apply_fill(_fill(OrderSide.SELL, 10, 110.0))
        self.assertAlmostEqual(p.realized_pnl(), 100.0)
        self.assertAlmostEqual(p.cash, 10_100.0)
        self.assertAlmostEqual(p.positions["SPY"].qty, 0.0)

    def test_averaging_in(self) -> None:
        p = Portfolio(cash=10_000.0)
        p.apply_fill(_fill(OrderSide.BUY, 10, 100.0))
        p.apply_fill(_fill(OrderSide.BUY, 10, 110.0))
        pos = p.positions["SPY"]
        self.assertAlmostEqual(pos.qty, 20)
        self.assertAlmostEqual(pos.avg_price, 105.0)

    def test_flip_short(self) -> None:
        p = Portfolio(cash=10_000.0)
        p.apply_fill(_fill(OrderSide.BUY, 10, 100.0))
        p.apply_fill(_fill(OrderSide.SELL, 15, 110.0))
        pos = p.positions["SPY"]
        self.assertAlmostEqual(pos.qty, -5)
        self.assertAlmostEqual(pos.avg_price, 110.0)
        self.assertAlmostEqual(pos.realized_pnl, 100.0)

    def test_equity_includes_marks(self) -> None:
        p = Portfolio(cash=5_000.0)
        p.apply_fill(_fill(OrderSide.BUY, 10, 100.0))
        p.update_mark("SPY", 105.0)
        self.assertAlmostEqual(p.equity(), 5_000.0 - 1_000.0 + 10 * 105.0)

    def test_fees_reduce_cash(self) -> None:
        p = Portfolio(cash=1_000.0)
        p.apply_fill(Fill(
            order_id="x",
            symbol="SPY",
            side=OrderSide.BUY,
            qty=1,
            price=100.0,
            ts=datetime(2026, 4, 12, tzinfo=timezone.utc),
            fee=2.5,
        ))
        self.assertAlmostEqual(p.cash, 1_000.0 - 100.0 - 2.5)


if __name__ == "__main__":
    unittest.main()
