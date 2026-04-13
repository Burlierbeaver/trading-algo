from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from decimal import Decimal

from risk_manager.brokers.simulated import SimulatedBroker
from risk_manager.engine import RiskEngine
from risk_manager.ledger import Ledger
from risk_manager.persistence import SQLiteStore
from risk_manager.types import Fill, Mode, Order, Reject, Side

from conftest import make_intent


D = Decimal


def _engine(base_config, sectors, tmp_path, starting_cash=D("100000"), broker=None):
    db = tmp_path / f"engine_{id(tmp_path)}.db"
    store = SQLiteStore(db)
    ledger = Ledger(starting_cash=starting_cash)
    ledger.ensure_sod(datetime(2026, 4, 12, 14, 30, tzinfo=timezone.utc))
    cfg = dataclasses.replace(base_config, db_path=db)
    eng = RiskEngine(
        cfg,
        ledger,
        sectors,
        store,
        broker=broker,
        now=lambda: datetime(2026, 4, 12, 14, 30, tzinfo=timezone.utc),
    )
    return eng, store


def test_engine_approves_within_limits(base_config, sectors, tmp_path):
    eng, store = _engine(base_config, sectors, tmp_path)
    eng.mark({"AAPL": D("100")})
    decision = eng.check(make_intent(symbol="AAPL", qty=10))
    assert isinstance(decision, Order)
    entries = store.audit_entries()
    assert entries[0]["decision"] == "approve"


def test_engine_rejects_oversized_position(base_config, sectors, tmp_path):
    eng, _ = _engine(base_config, sectors, tmp_path)
    eng.mark({"MSFT": D("100")})
    decision = eng.check(make_intent(symbol="MSFT", qty=300))
    assert isinstance(decision, Reject)
    assert decision.rule == "position_cap"


def test_engine_rejects_when_kill_switch_set(base_config, sectors, tmp_path):
    eng, _ = _engine(base_config, sectors, tmp_path)
    eng.mark({"AAPL": D("100")})
    eng.kill("ops halt")
    decision = eng.check(make_intent(symbol="AAPL", qty=1))
    assert isinstance(decision, Reject)
    assert decision.rule == "kill_switch"
    assert "ops halt" in decision.reason


def test_engine_kill_file_trips_on_next_check(base_config, sectors, tmp_path):
    cfg = dataclasses.replace(base_config, mode=Mode.PAPER, workdir=tmp_path)
    db = tmp_path / "paper.db"
    store = SQLiteStore(db)
    ledger = Ledger(starting_cash=D("100000"))
    ledger.ensure_sod(datetime(2026, 4, 12, 14, 30, tzinfo=timezone.utc))
    eng = RiskEngine(
        dataclasses.replace(cfg, db_path=db),
        ledger,
        sectors,
        store,
        now=lambda: datetime(2026, 4, 12, 14, 30, tzinfo=timezone.utc),
    )
    eng.mark({"AAPL": D("100")})
    # First check passes
    assert isinstance(eng.check(make_intent("AAPL", qty=1)), Order)
    # Drop the kill file
    (tmp_path / "KILL").write_text("halt")
    decision = eng.check(make_intent("AAPL", qty=1))
    assert isinstance(decision, Reject)
    assert decision.rule == "kill_switch"


def test_engine_clear_kill_restores_normal_operation(base_config, sectors, tmp_path):
    eng, _ = _engine(base_config, sectors, tmp_path)
    eng.mark({"AAPL": D("100")})
    eng.kill("test")
    assert isinstance(eng.check(make_intent("AAPL", qty=1)), Reject)
    eng.clear_kill("ops", "resuming")
    assert isinstance(eng.check(make_intent("AAPL", qty=1)), Order)


def test_engine_on_fill_updates_ledger_and_audits(base_config, sectors, tmp_path):
    eng, store = _engine(base_config, sectors, tmp_path)
    eng.mark({"AAPL": D("100")})
    decision = eng.check(make_intent("AAPL", qty=10))
    assert isinstance(decision, Order)
    eng.on_fill(
        Fill(
            symbol="AAPL",
            side=Side.BUY,
            qty=D("10"),
            price=D("100"),
            client_order_id=decision.intent.client_order_id,
        )
    )
    assert eng.ledger.get_position("AAPL").qty == D("10")
    assert eng.ledger.cash() == D("99000")


def test_engine_notional_order_requires_reference_price(base_config, sectors, tmp_path):
    eng, _ = _engine(base_config, sectors, tmp_path)
    decision = eng.check(
        make_intent(symbol="UNKMARK", qty=None, notional=Decimal("1000"))
    )
    assert isinstance(decision, Reject)
    assert decision.rule == "sizing"


def test_engine_notional_order_uses_mark_when_available(base_config, sectors, tmp_path):
    eng, _ = _engine(base_config, sectors, tmp_path)
    eng.mark({"AAPL": D("100")})
    decision = eng.check(
        make_intent(symbol="AAPL", qty=None, notional=Decimal("1000"))
    )
    assert isinstance(decision, Order)


def test_engine_reconcile_detects_position_drift(base_config, sectors, tmp_path):
    from risk_manager.types import Position

    broker = SimulatedBroker(
        starting_cash=D("100000"),
        positions={"AAPL": Position("AAPL", D("5"), D("100"))},
    )
    eng, _ = _engine(base_config, sectors, tmp_path, broker=broker)
    ok, reason = eng.reconcile()
    assert not ok
    assert "position drift" in reason
    assert eng.status().halted


def test_engine_reconcile_detects_cash_drift(base_config, sectors, tmp_path):
    broker = SimulatedBroker(starting_cash=D("50000"))
    eng, _ = _engine(base_config, sectors, tmp_path, broker=broker)
    ok, reason = eng.reconcile()
    assert not ok
    assert "cash drift" in reason


def test_engine_reconcile_ok_when_aligned(base_config, sectors, tmp_path):
    broker = SimulatedBroker(starting_cash=D("100000"))
    eng, _ = _engine(base_config, sectors, tmp_path, broker=broker)
    ok, reason = eng.reconcile()
    assert ok
    assert reason is None


def test_engine_rule_exception_trips_kill(base_config, sectors, tmp_path):
    from risk_manager.rules.base import RuleResult

    class Boom:
        name = "boom"

        def evaluate(self, ctx):  # noqa: ARG002
            raise RuntimeError("explode")

    db = tmp_path / "boom.db"
    store = SQLiteStore(db)
    ledger = Ledger(starting_cash=D("100000"))
    ledger.ensure_sod(datetime(2026, 4, 12, 14, 30, tzinfo=timezone.utc))
    cfg = dataclasses.replace(base_config, db_path=db)
    eng = RiskEngine(
        cfg,
        ledger,
        sectors,
        store,
        rules=[Boom()],
        now=lambda: datetime(2026, 4, 12, 14, 30, tzinfo=timezone.utc),
    )
    eng.mark({"AAPL": D("100")})
    decision = eng.check(make_intent("AAPL", qty=1))
    assert isinstance(decision, Reject)
    assert decision.rule == "internal-error"
    assert eng.status().halted
