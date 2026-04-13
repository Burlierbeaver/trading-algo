from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from threading import RLock
from typing import Callable

from .audit import AuditLog
from .brokers.protocol import BrokerAdapter
from .config import RiskConfig
from .ledger import Ledger
from .persistence import KillState, SQLiteStore
from .rules import (
    DailyLossRule,
    KillSwitchRule,
    PositionCapRule,
    RuleContext,
    SectorExposureRule,
)
from .rules.base import Rule
from .sectors import SectorClassifier
from .types import (
    Decision,
    Fill,
    Mode,
    Order,
    PortfolioSnapshot,
    Reject,
    RiskStatus,
    Side,
    TradeIntent,
)


DEFAULT_RULES: tuple[type, ...] = (
    KillSwitchRule,
    DailyLossRule,
    PositionCapRule,
    SectorExposureRule,
)


class RiskEngine:
    """Orchestrator. Holds the ledger, kill state, and rule list. The only
    entry point callers should use: `check`, `on_fill`, `mark`, `kill`,
    `clear_kill`, `status`, `reconcile`.
    """

    def __init__(
        self,
        config: RiskConfig,
        ledger: Ledger,
        sectors: SectorClassifier,
        store: SQLiteStore,
        broker: BrokerAdapter | None = None,
        rules: list[Rule] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._ledger = ledger
        self._sectors = sectors
        self._store = store
        self._audit = AuditLog(store)
        self._broker = broker
        self._rules: list[Rule] = rules if rules is not None else [cls() for cls in DEFAULT_RULES]
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._lock = RLock()
        self._kill_file: Path | None = self._resolve_kill_file()

        existing = store.load_kill_state()
        if config.kill_switch and not existing.tripped:
            self._trip_locked("config flag set at startup")
        else:
            self._kill_state = existing

    # ── construction helpers ────────────────────────────────────────────
    @classmethod
    def from_config(cls, config: RiskConfig, broker: BrokerAdapter | None = None) -> "RiskEngine":
        config.workdir.mkdir(parents=True, exist_ok=True) if config.mode is not Mode.BACKTEST else None
        db_path = config.resolved_db_path()
        if str(db_path) != ":memory:":
            db_path.parent.mkdir(parents=True, exist_ok=True)
        store = SQLiteStore(db_path)
        sectors = SectorClassifier.from_file(config.sectors_path)
        ledger = Ledger()
        # restore from store if present
        cash = store.load_cash()
        positions = store.load_positions()
        if cash is not None or positions:
            ledger.set_starting_state(cash or Decimal("0"), positions)
        return cls(config, ledger, sectors, store, broker=broker)

    # ── introspection ───────────────────────────────────────────────────
    @property
    def config(self) -> RiskConfig:
        return self._config

    @property
    def ledger(self) -> Ledger:
        return self._ledger

    @property
    def store(self) -> SQLiteStore:
        return self._store

    def status(self) -> RiskStatus:
        with self._lock:
            self._refresh_kill_file_locked()
            snap = self._ledger.snapshot(self._now())
            sod = snap.sod_equity or Decimal("1")
            pnl_pct = (snap.equity - snap.sod_equity) / sod if sod != 0 else Decimal("0")
            return RiskStatus(
                halted=self._kill_state.tripped,
                halt_reason=self._kill_state.reason,
                equity=snap.equity,
                sod_equity=snap.sod_equity,
                daily_pnl_pct=pnl_pct,
            )

    # ── primary API ─────────────────────────────────────────────────────
    def check(self, intent: TradeIntent) -> Decision:
        with self._lock:
            self._refresh_kill_file_locked()
            snapshot = self._ledger.snapshot(self._now())
            ref_price = self._reference_price(intent, snapshot)
            try:
                post_qty = self._post_trade_qty(intent, snapshot, ref_price)
            except _CheckError as e:
                decision: Decision = Reject(intent, "sizing", str(e))
                self._audit.record(decision, snapshot)
                return decision

            ctx = RuleContext(
                intent=intent,
                snapshot=snapshot,
                ref_price=ref_price,
                post_qty=post_qty,
                config=self._config,
                sectors=self._sectors,
                kill_tripped=self._kill_state.tripped,
                kill_reason=self._kill_state.reason,
            )
            decision = self._evaluate_rules(ctx)
            self._audit.record(decision, snapshot)
            return decision

    def on_fill(self, fill: Fill) -> None:
        with self._lock:
            self._ledger.apply_fill(fill)
            self._store.record_fill(fill)
            snap = self._ledger.snapshot(self._now())
            self._store.save_snapshot(snap, snap.positions.values())

    def mark(self, prices: dict[str, Decimal]) -> None:
        with self._lock:
            decimal_prices = {k: Decimal(v) for k, v in prices.items()}
            self._ledger.mark(decimal_prices)
            self._ledger.ensure_sod(self._now())

    def kill(self, reason: str) -> None:
        with self._lock:
            self._trip_locked(reason)

    def clear_kill(self, operator: str, reason: str) -> None:
        with self._lock:
            self._kill_state = KillState(False, None, None)
            self._store.save_kill_state(self._kill_state)
            # Record the clear as an audit entry via a synthetic reject->approve intent.
            # Simpler: log directly through the store's audit table with a placeholder.
            # Keeping it lightweight here — operators can grep audit_log for 'clear'.
            self._store._conn.execute(  # noqa: SLF001  (internal use)
                "INSERT INTO audit_log(ts, decision, rule, reason, intent_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    self._now().isoformat(),
                    "kill_cleared",
                    None,
                    f"cleared by {operator}: {reason}",
                    "{}",
                ),
            )

    def reconcile(self) -> tuple[bool, str | None]:
        """Compare ledger against broker state. Returns (ok, reason_if_drift).
        Trips kill switch if drift exceeds tolerances.
        """
        if self._broker is None:
            return True, None
        with self._lock:
            snap = self._ledger.snapshot(self._now())
            try:
                broker_cash = self._broker.get_cash()
                broker_positions = self._broker.get_positions()
            except Exception as e:  # noqa: BLE001
                raise
            tol = self._config.reconciler
            # Cash drift
            if snap.cash != 0 or broker_cash != 0:
                if snap.cash == 0:
                    cash_diff_pct = Decimal("1")
                else:
                    cash_diff_pct = abs(broker_cash - snap.cash) / abs(snap.cash)
                if cash_diff_pct > tol.cash_tolerance_pct:
                    reason = (
                        f"cash drift {cash_diff_pct:.4%} "
                        f"(ledger={snap.cash} broker={broker_cash})"
                    )
                    self._trip_locked(reason)
                    return False, reason
            # Position drift
            symbols = set(snap.positions.keys()) | set(broker_positions.keys())
            for sym in symbols:
                ledger_qty = snap.positions.get(sym)
                ledger_qty = ledger_qty.qty if ledger_qty else Decimal("0")
                broker_qty = broker_positions.get(sym)
                broker_qty = broker_qty.qty if broker_qty else Decimal("0")
                diff = abs(broker_qty - ledger_qty)
                if diff > tol.qty_tolerance:
                    reason = (
                        f"position drift on {sym}: "
                        f"ledger={ledger_qty} broker={broker_qty} diff={diff}"
                    )
                    self._trip_locked(reason)
                    return False, reason
            return True, None

    # ── internals ───────────────────────────────────────────────────────
    def _evaluate_rules(self, ctx: RuleContext) -> Decision:
        for rule in self._rules:
            try:
                result = rule.evaluate(ctx)
            except Exception as e:  # noqa: BLE001
                self._trip_locked(f"internal error in rule {rule.name}: {e!r}")
                return Reject(ctx.intent, "internal-error", f"rule {rule.name} raised {e!r}")
            if result.rejected:
                return Reject(ctx.intent, result.rule, result.reason or "rejected")
        return Order(ctx.intent, approval_id=uuid.uuid4().hex, approved_at=self._now())

    def _reference_price(
        self, intent: TradeIntent, snap: PortfolioSnapshot
    ) -> Decimal | None:
        if intent.limit_price is not None:
            return intent.limit_price
        sym = intent.symbol.upper()
        mark = snap.marks.get(sym)
        if mark is not None:
            return mark
        # Fallback to broker quote if available.
        if self._broker is not None:
            try:
                return self._broker.get_quote(sym)
            except Exception:  # noqa: BLE001
                return None
        return None

    def _post_trade_qty(
        self,
        intent: TradeIntent,
        snap: PortfolioSnapshot,
        ref_price: Decimal | None,
    ) -> Decimal:
        sym = intent.symbol.upper()
        pos = snap.positions.get(sym)
        current = pos.qty if pos is not None else Decimal("0")
        if intent.qty is not None:
            signed = intent.qty if intent.side is Side.BUY else -intent.qty
            return current + signed
        assert intent.notional is not None
        if ref_price is None:
            raise _CheckError(
                f"notional order for {sym} requires a reference price (limit or mark)"
            )
        qty = intent.notional / ref_price
        signed = qty if intent.side is Side.BUY else -qty
        return current + signed

    def _trip_locked(self, reason: str) -> None:
        state = KillState(True, reason, self._now().isoformat())
        self._kill_state = state
        self._store.save_kill_state(state)

    def _refresh_kill_file_locked(self) -> None:
        if self._kill_file is None:
            return
        if self._kill_file.exists() and not self._kill_state.tripped:
            self._trip_locked(f"kill file present: {self._kill_file}")

    def _resolve_kill_file(self) -> Path | None:
        if self._config.mode is Mode.BACKTEST:
            return None
        return self._config.workdir / "KILL"


class _CheckError(Exception):
    pass
