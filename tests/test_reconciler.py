from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from decimal import Decimal

from risk_manager.brokers.simulated import SimulatedBroker
from risk_manager.engine import RiskEngine
from risk_manager.ledger import Ledger
from risk_manager.persistence import SQLiteStore
from risk_manager.reconciler import Reconciler


D = Decimal


class ExplodingBroker:
    def get_cash(self):
        raise RuntimeError("network down")

    def get_positions(self):
        raise RuntimeError("network down")

    def get_quote(self, symbol):
        raise RuntimeError("network down")


def _engine(base_config, sectors, tmp_path, broker):
    db = tmp_path / "recon.db"
    store = SQLiteStore(db)
    ledger = Ledger(starting_cash=D("100000"))
    ledger.ensure_sod(datetime(2026, 4, 12, 14, 30, tzinfo=timezone.utc))
    cfg = dataclasses.replace(base_config, db_path=db)
    return RiskEngine(
        cfg,
        ledger,
        sectors,
        store,
        broker=broker,
        now=lambda: datetime(2026, 4, 12, 14, 30, tzinfo=timezone.utc),
    )


def test_reconciler_tick_trips_kill_on_drift(base_config, sectors, tmp_path):
    from risk_manager.types import Position

    broker = SimulatedBroker(
        starting_cash=D("100000"),
        positions={"AAPL": Position("AAPL", D("3"), D("100"))},
    )
    eng = _engine(base_config, sectors, tmp_path, broker)
    recon = Reconciler(eng)
    recon.tick()
    assert eng.status().halted


def test_reconciler_trips_after_consecutive_failures(base_config, sectors, tmp_path):
    eng = _engine(base_config, sectors, tmp_path, ExplodingBroker())
    recon = Reconciler(eng, max_consecutive_failures=3)
    for _ in range(2):
        recon.tick()
    assert not eng.status().halted
    recon.tick()  # third failure
    assert eng.status().halted
    assert "consecutive broker failures" in eng.status().halt_reason


def test_reconciler_resets_failure_counter_on_success(base_config, sectors, tmp_path):
    class FlakyBroker(ExplodingBroker):
        def __init__(self):
            self.calls = 0

        def get_cash(self):
            self.calls += 1
            if self.calls <= 2:
                raise RuntimeError("transient")
            return D("100000")

        def get_positions(self):
            return {}

    eng = _engine(base_config, sectors, tmp_path, FlakyBroker())
    recon = Reconciler(eng, max_consecutive_failures=5)
    recon.tick()
    recon.tick()
    recon.tick()  # succeeds, resets counter
    assert not eng.status().halted
