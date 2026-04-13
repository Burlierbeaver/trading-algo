from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from risk_manager.persistence import KillState, SQLiteStore
from risk_manager.types import Fill, Order, Position, Reject, Side, TradeIntent, OrderType


D = Decimal


def test_cash_and_position_round_trip(tmp_path):
    store = SQLiteStore(tmp_path / "t.db")
    store.save_cash(D("12345.67"))
    store.save_position(Position("AAPL", D("10"), D("100.5"), D("25")))
    store.save_position(Position("MSFT", D("-5"), D("350"), D("0")))
    assert store.load_cash() == D("12345.67")
    positions = store.load_positions()
    assert positions["AAPL"].qty == D("10")
    assert positions["AAPL"].avg_cost == D("100.5")
    assert positions["MSFT"].qty == D("-5")


def test_kill_state_round_trip(tmp_path):
    store = SQLiteStore(tmp_path / "t.db")
    assert not store.load_kill_state().tripped
    store.save_kill_state(KillState(True, "manual", "2026-04-12T14:30:00+00:00"))
    ks = store.load_kill_state()
    assert ks.tripped and ks.reason == "manual"


def test_audit_log_records_approve_and_reject(tmp_path):
    store = SQLiteStore(tmp_path / "t.db")
    intent = TradeIntent(
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        qty=D("1"),
        client_order_id="c1",
    )
    store.record_decision(Order(intent, approval_id="a1"), None)
    store.record_decision(Reject(intent, "position_cap", "too big"), None)
    entries = store.audit_entries()
    assert len(entries) == 2
    assert entries[0]["decision"] == "reject"
    assert entries[1]["decision"] == "approve"


def test_fill_recording(tmp_path):
    store = SQLiteStore(tmp_path / "t.db")
    fill = Fill(
        symbol="AAPL",
        side=Side.BUY,
        qty=D("10"),
        price=D("100"),
        client_order_id="c1",
    )
    store.record_fill(fill)
    # Raw verification through the underlying connection.
    cur = store._conn.execute("SELECT symbol, qty, price FROM fills")  # noqa: SLF001
    row = cur.fetchone()
    assert row == ("AAPL", "10", "100")


def test_daily_mark(tmp_path):
    store = SQLiteStore(tmp_path / "t.db")
    store.save_sod("2026-04-12", D("100000"))
    assert store.load_sod("2026-04-12") == D("100000")
    assert store.load_sod("2026-04-13") is None
