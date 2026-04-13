from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from threading import RLock
from typing import Any, Iterable

from .types import Decision, Fill, Order, PortfolioSnapshot, Position, Reject, TradeIntent


SCHEMA = """
CREATE TABLE IF NOT EXISTS cash (
    id INTEGER PRIMARY KEY CHECK (id = 0),
    amount TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    symbol TEXT PRIMARY KEY,
    qty TEXT NOT NULL,
    avg_cost TEXT NOT NULL,
    realized_pnl TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_marks (
    trade_date TEXT PRIMARY KEY,
    sod_equity TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    decision TEXT NOT NULL,
    rule TEXT,
    reason TEXT,
    intent_json TEXT NOT NULL,
    snapshot_json TEXT
);

CREATE TABLE IF NOT EXISTS kill_state (
    id INTEGER PRIMARY KEY CHECK (id = 0),
    tripped INTEGER NOT NULL,
    reason TEXT,
    tripped_at TEXT
);

CREATE TABLE IF NOT EXISTS fills (
    client_order_id TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty TEXT NOT NULL,
    price TEXT NOT NULL,
    ts TEXT NOT NULL
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _intent_to_json(intent: TradeIntent) -> str:
    return json.dumps(
        {
            "symbol": intent.symbol,
            "side": intent.side.value,
            "order_type": intent.order_type.value,
            "qty": str(intent.qty) if intent.qty is not None else None,
            "notional": str(intent.notional) if intent.notional is not None else None,
            "limit_price": (
                str(intent.limit_price) if intent.limit_price is not None else None
            ),
            "client_order_id": intent.client_order_id,
            "strategy_id": intent.strategy_id,
            "ts": intent.ts.isoformat(),
        }
    )


def _snapshot_to_json(snap: PortfolioSnapshot | None) -> str | None:
    if snap is None:
        return None
    return json.dumps(
        {
            "ts": snap.ts.isoformat(),
            "cash": str(snap.cash),
            "equity": str(snap.equity),
            "sod_equity": str(snap.sod_equity),
            "positions": {
                sym: {"qty": str(p.qty), "avg_cost": str(p.avg_cost)}
                for sym, p in snap.positions.items()
                if p.qty != 0
            },
        }
    )


@dataclass(frozen=True)
class KillState:
    tripped: bool
    reason: str | None
    tripped_at: str | None


class SQLiteStore:
    """Thin wrapper around a SQLite DB for risk-manager persistence.

    Single connection with a reentrant lock — safe for the engine's synchronous
    API. The reconciler uses its own connection.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._lock = RLock()

    @property
    def path(self) -> str:
        return self._path

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # Ledger snapshot I/O
    def save_cash(self, amount: Decimal) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO cash(id, amount, updated_at) VALUES (0, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET amount=excluded.amount, updated_at=excluded.updated_at",
                (str(amount), _now_iso()),
            )

    def save_position(self, pos: Position) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO positions(symbol, qty, avg_cost, realized_pnl, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(symbol) DO UPDATE SET qty=excluded.qty, "
                "avg_cost=excluded.avg_cost, realized_pnl=excluded.realized_pnl, "
                "updated_at=excluded.updated_at",
                (pos.symbol, str(pos.qty), str(pos.avg_cost), str(pos.realized_pnl), _now_iso()),
            )

    def save_sod(self, trade_date: str, sod_equity: Decimal) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO daily_marks(trade_date, sod_equity, recorded_at) VALUES (?, ?, ?) "
                "ON CONFLICT(trade_date) DO UPDATE SET sod_equity=excluded.sod_equity, "
                "recorded_at=excluded.recorded_at",
                (trade_date, str(sod_equity), _now_iso()),
            )

    def load_cash(self) -> Decimal | None:
        with self._lock:
            cur = self._conn.execute("SELECT amount FROM cash WHERE id = 0")
            row = cur.fetchone()
            return Decimal(row[0]) if row else None

    def load_positions(self) -> dict[str, Position]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT symbol, qty, avg_cost, realized_pnl FROM positions"
            )
            out: dict[str, Position] = {}
            for sym, qty, avg, rpnl in cur.fetchall():
                out[sym] = Position(sym, Decimal(qty), Decimal(avg), Decimal(rpnl))
            return out

    def load_sod(self, trade_date: str) -> Decimal | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT sod_equity FROM daily_marks WHERE trade_date = ?", (trade_date,)
            )
            row = cur.fetchone()
            return Decimal(row[0]) if row else None

    # Audit
    def record_decision(
        self,
        decision: Decision,
        snapshot: PortfolioSnapshot | None,
    ) -> None:
        with self._lock:
            if isinstance(decision, Order):
                kind = "approve"
                rule: str | None = None
                reason: str | None = None
                intent = decision.intent
                ts = decision.approved_at
            else:
                kind = "reject"
                rule = decision.rule
                reason = decision.reason
                intent = decision.intent
                ts = decision.rejected_at
            self._conn.execute(
                "INSERT INTO audit_log(ts, decision, rule, reason, intent_json, snapshot_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    ts.isoformat(),
                    kind,
                    rule,
                    reason,
                    _intent_to_json(intent),
                    _snapshot_to_json(snapshot),
                ),
            )

    def record_fill(self, fill: Fill) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO fills(client_order_id, symbol, side, qty, price, ts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    fill.client_order_id,
                    fill.symbol,
                    fill.side.value,
                    str(fill.qty),
                    str(fill.price),
                    fill.ts.isoformat(),
                ),
            )

    def audit_entries(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT ts, decision, rule, reason, intent_json, snapshot_json "
                "FROM audit_log ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            out = []
            for ts, decision, rule, reason, intent_json, snap_json in cur.fetchall():
                out.append(
                    {
                        "ts": ts,
                        "decision": decision,
                        "rule": rule,
                        "reason": reason,
                        "intent": json.loads(intent_json),
                        "snapshot": json.loads(snap_json) if snap_json else None,
                    }
                )
            return out

    # Kill state
    def save_kill_state(self, state: KillState) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO kill_state(id, tripped, reason, tripped_at) VALUES (0, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET tripped=excluded.tripped, "
                "reason=excluded.reason, tripped_at=excluded.tripped_at",
                (1 if state.tripped else 0, state.reason, state.tripped_at),
            )

    def load_kill_state(self) -> KillState:
        with self._lock:
            cur = self._conn.execute(
                "SELECT tripped, reason, tripped_at FROM kill_state WHERE id = 0"
            )
            row = cur.fetchone()
            if not row:
                return KillState(False, None, None)
            return KillState(bool(row[0]), row[1], row[2])

    def save_snapshot(self, snapshot: PortfolioSnapshot, iter_positions: Iterable[Position]) -> None:
        with self._lock:
            self.save_cash(snapshot.cash)
            for pos in iter_positions:
                self.save_position(pos)
            td = snapshot.ts.astimezone(timezone.utc).date().isoformat()
            self.save_sod(td, snapshot.sod_equity)
