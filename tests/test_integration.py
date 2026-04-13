from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from decimal import Decimal

from risk_manager.brokers.simulated import SimulatedBroker
from risk_manager.config import PositionCap
from risk_manager.engine import RiskEngine
from risk_manager.ledger import Ledger
from risk_manager.persistence import SQLiteStore
from risk_manager.types import Fill, Order, Reject, Side

from conftest import make_intent


D = Decimal


def test_backtest_end_to_end(base_config, sectors, tmp_path):
    """A scripted backtest: intents → fills → marks → more intents.

    Verifies the ledger evolves correctly, audit log captures each decision,
    and sector/position limits fire as the portfolio grows. Uses relaxed
    per-symbol caps so sector-level exposure is the binding constraint.
    """
    ts = datetime(2026, 4, 12, 14, 30, tzinfo=timezone.utc)
    db = tmp_path / "bt.db"
    store = SQLiteStore(db)
    ledger = Ledger(starting_cash=D("100000"))
    ledger.ensure_sod(ts)
    cfg = dataclasses.replace(
        base_config,
        db_path=db,
        default_position_cap=PositionCap(D("25000"), D("0.15")),
        symbol_position_caps={},
        default_sector_cap_pct=D("0.20"),
    )
    broker = SimulatedBroker(starting_cash=D("100000"))
    eng = RiskEngine(cfg, ledger, sectors, store, broker=broker, now=lambda: ts)

    eng.mark({"AAPL": D("100"), "MSFT": D("100"), "NVDA": D("100"), "JPM": D("100")})

    # 100 AAPL @ 100 = 10k (10% of equity, Tech = 10k = 10%) — ok
    d1 = eng.check(make_intent("AAPL", qty=100))
    assert isinstance(d1, Order)
    eng.on_fill(Fill("AAPL", Side.BUY, D("100"), D("100"), d1.intent.client_order_id))

    # 100 MSFT @ 100 = 10k. Post-trade Tech = 20k = 20% (at sector cap edge) — ok
    d2 = eng.check(make_intent("MSFT", qty=100))
    assert isinstance(d2, Order)
    eng.on_fill(Fill("MSFT", Side.BUY, D("100"), D("100"), d2.intent.client_order_id))

    # 10 NVDA @ 100 = 1k (under position cap). Post Tech = 21k = 21% > 20% — sector cap rejects.
    d3 = eng.check(make_intent("NVDA", qty=10))
    assert isinstance(d3, Reject)
    assert d3.rule == "sector_exposure"

    # Cross-sector JPM is fine: 100 @ 100 = 10k = 10% Financials
    d4 = eng.check(make_intent("JPM", qty=100))
    assert isinstance(d4, Order)

    entries = store.audit_entries()
    assert len(entries) == 4
    assert [e["decision"] for e in entries[::-1]] == [
        "approve",
        "approve",
        "reject",
        "approve",
    ]


def test_daily_loss_trip_then_kill_clear_cycle(base_config, sectors, tmp_path):
    ts = datetime(2026, 4, 12, 14, 30, tzinfo=timezone.utc)
    db = tmp_path / "dl.db"
    store = SQLiteStore(db)
    ledger = Ledger(starting_cash=D("100000"))
    ledger.ensure_sod(ts)
    cfg = dataclasses.replace(base_config, db_path=db)
    eng = RiskEngine(cfg, ledger, sectors, store, now=lambda: ts)

    eng.mark({"AAPL": D("100")})
    # Open long via fill
    eng.on_fill(Fill("AAPL", Side.BUY, D("100"), D("100"), "c0"))  # $10k position
    # Mark drops 30%: equity = 90000 + 7000 = 97000, but we started at 100k; -3%
    eng.mark({"AAPL": D("70")})
    # Risk-increasing buy should be rejected
    d1 = eng.check(make_intent("AAPL", qty=1, side=Side.BUY))
    assert isinstance(d1, Reject)
    assert d1.rule == "daily_loss"
    # Closing sell still allowed
    d2 = eng.check(make_intent("AAPL", qty=10, side=Side.SELL))
    assert isinstance(d2, Order)
