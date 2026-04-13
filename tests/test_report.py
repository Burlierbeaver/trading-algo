from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backtester.portfolio import Fill, Portfolio
from backtester.report import build_report
from backtester.strategy import OrderSide


def _fill(side: OrderSide, qty: float, price: float, symbol: str = "SPY", t: int = 0) -> Fill:
    return Fill(
        order_id="x",
        symbol=symbol,
        side=side,
        qty=qty,
        price=price,
        ts=datetime(2026, 4, 12, tzinfo=timezone.utc) + timedelta(seconds=t),
    )


class ReportTests(unittest.TestCase):
    def test_single_round_trip_report(self) -> None:
        p = Portfolio(cash=10_000.0)
        p.apply_fill(_fill(OrderSide.BUY, 10, 100.0))
        p.apply_fill(_fill(OrderSide.SELL, 10, 110.0, t=1))
        report = build_report(
            portfolio=p,
            equity_curve=[("2026-04-12T00:00:00+00:00", 10_000.0), ("2026-04-12T00:00:01+00:00", 10_100.0)],
            starting_cash=10_000.0,
            mode="historical",
            seed=None,
        )
        self.assertAlmostEqual(report.ending_equity, 10_100.0)
        self.assertAlmostEqual(report.trades.realized_pnl, 100.0)
        self.assertEqual(report.trades.total_fills, 2)
        self.assertGreater(report.trades.win_rate, 0.0)

    def test_drawdown_computation(self) -> None:
        p = Portfolio(cash=1_000.0)
        curve = [
            ("1", 1_000.0),
            ("2", 1_200.0),
            ("3", 900.0),
            ("4", 1_100.0),
        ]
        report = build_report(
            portfolio=p,
            equity_curve=curve,
            starting_cash=1_000.0,
            mode="historical",
            seed=None,
        )
        self.assertAlmostEqual(report.risk.max_drawdown, 300.0)
        self.assertAlmostEqual(report.risk.max_drawdown_pct, 25.0)

    def test_to_json_writes_file(self) -> None:
        p = Portfolio(cash=1_000.0)
        report = build_report(
            portfolio=p,
            equity_curve=[("1", 1_000.0)],
            starting_cash=1_000.0,
            mode="historical",
            seed=42,
        )
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "r.json"
            report.to_json(path)
            data = json.loads(path.read_text())
            self.assertEqual(data["seed"], 42)
            self.assertEqual(data["mode"], "historical")


if __name__ == "__main__":
    unittest.main()
