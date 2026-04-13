from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from backtester import SignalEvent

from trading_algo.backtest import run_backtest


def test_runs_signal_events_through_default_strategy():
    t0 = datetime.now(timezone.utc)
    events = [
        SignalEvent(ts=t0, symbol="AAPL", name="strong", value=0.8, confidence=0.9),
        SignalEvent(ts=t0 + timedelta(minutes=1), symbol="AAPL", name="weak", value=0.1, confidence=0.3),
    ]

    result = run_backtest(events, starting_cash=Decimal("10000"))

    assert result.report.mode == "historical"
    assert result.report.starting_cash == 10000.0
    assert isinstance(result.orders_submitted, int)
