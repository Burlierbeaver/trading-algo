from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from risk_manager.ledger import Ledger
from risk_manager.types import Fill, Side


D = Decimal


def _fill(symbol="AAPL", side=Side.BUY, qty="10", price="100"):
    return Fill(
        symbol=symbol,
        side=side,
        qty=Decimal(qty),
        price=Decimal(price),
        client_order_id="c1",
    )


def test_long_open_updates_cash_and_position():
    ledger = Ledger(starting_cash=D("10000"))
    ledger.apply_fill(_fill(qty="10", price="100"))
    pos = ledger.get_position("AAPL")
    assert pos.qty == D("10")
    assert pos.avg_cost == D("100")
    assert ledger.cash() == D("9000")


def test_long_add_averages_cost():
    ledger = Ledger(starting_cash=D("10000"))
    ledger.apply_fill(_fill(qty="10", price="100"))
    ledger.apply_fill(_fill(qty="10", price="110"))
    pos = ledger.get_position("AAPL")
    assert pos.qty == D("20")
    assert pos.avg_cost == D("105")
    assert ledger.cash() == D("7900")


def test_long_partial_close_realizes_pnl():
    ledger = Ledger(starting_cash=D("10000"))
    ledger.apply_fill(_fill(qty="10", price="100"))
    ledger.apply_fill(_fill(side=Side.SELL, qty="4", price="120"))
    pos = ledger.get_position("AAPL")
    assert pos.qty == D("6")
    assert pos.avg_cost == D("100")
    assert pos.realized_pnl == D("80")  # (120-100)*4
    assert ledger.cash() == D("9480")   # 10000 - 1000 + 480


def test_long_full_close_flattens_and_realizes():
    ledger = Ledger(starting_cash=D("10000"))
    ledger.apply_fill(_fill(qty="10", price="100"))
    ledger.apply_fill(_fill(side=Side.SELL, qty="10", price="110"))
    pos = ledger.get_position("AAPL")
    assert pos.qty == D("0")
    assert pos.realized_pnl == D("100")
    assert ledger.cash() == D("10100")


def test_long_reversal_through_zero():
    ledger = Ledger(starting_cash=D("10000"))
    ledger.apply_fill(_fill(qty="10", price="100"))
    # sell 15 at 105: close long 10 (realize 50), then short 5 at 105
    ledger.apply_fill(_fill(side=Side.SELL, qty="15", price="105"))
    pos = ledger.get_position("AAPL")
    assert pos.qty == D("-5")
    assert pos.avg_cost == D("105")
    assert pos.realized_pnl == D("50")  # (105-100)*10
    assert ledger.cash() == D("10575")  # 10000 - 1000 + 1575


def test_short_open_then_cover_profit():
    ledger = Ledger(starting_cash=D("10000"))
    ledger.apply_fill(_fill(side=Side.SELL, qty="10", price="100"))
    ledger.apply_fill(_fill(side=Side.BUY, qty="10", price="80"))
    pos = ledger.get_position("AAPL")
    assert pos.qty == D("0")
    assert pos.realized_pnl == D("200")  # (80-100)*10 * long_sign=-1 = 200
    assert ledger.cash() == D("10200")


def test_mark_and_snapshot_compute_equity():
    ledger = Ledger(starting_cash=D("10000"))
    ledger.apply_fill(_fill(qty="10", price="100"))
    ledger.mark({"AAPL": Decimal("120")})
    ts = datetime(2026, 4, 12, 14, 30, tzinfo=timezone.utc)
    snap = ledger.snapshot(ts)
    assert snap.cash == D("9000")
    assert snap.market_value == D("1200")
    assert snap.equity == D("10200")
    assert snap.unrealized_pnl == D("200")


def test_sod_equity_captured_once_per_day():
    ledger = Ledger(starting_cash=D("10000"))
    d1 = datetime(2026, 4, 12, 14, 30, tzinfo=timezone.utc)
    d1_later = datetime(2026, 4, 12, 18, 0, tzinfo=timezone.utc)
    d2 = datetime(2026, 4, 13, 14, 30, tzinfo=timezone.utc)
    ledger.ensure_sod(d1)
    first = ledger.sod_equity()
    ledger.apply_fill(_fill(qty="10", price="100"))
    ledger.mark({"AAPL": Decimal("120")})
    ledger.ensure_sod(d1_later)
    assert ledger.sod_equity() == first  # still same day, SoD pinned
    ledger.ensure_sod(d2)
    assert ledger.sod_equity() == D("10200")  # new day, captured equity at rollover


def test_set_starting_state_restores_from_persistence():
    from risk_manager.types import Position
    ledger = Ledger()
    ledger.set_starting_state(
        cash=D("5000"),
        positions={"AAPL": Position("AAPL", D("10"), D("100"), D("50"))},
        sod_equity=D("5500"),
    )
    assert ledger.cash() == D("5000")
    assert ledger.get_position("AAPL").qty == D("10")
    assert ledger.sod_equity() == D("5500")
