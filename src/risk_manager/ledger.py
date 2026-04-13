from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from threading import RLock

from .types import Fill, PortfolioSnapshot, Position, Side


@dataclass
class _MutablePosition:
    symbol: str
    qty: Decimal
    avg_cost: Decimal
    realized_pnl: Decimal

    def frozen(self) -> Position:
        return Position(
            symbol=self.symbol,
            qty=self.qty,
            avg_cost=self.avg_cost,
            realized_pnl=self.realized_pnl,
        )


class Ledger:
    """Authoritative in-memory position + cash ledger.

    Long positions have positive qty; shorts are negative. avg_cost is the VWAP
    of the currently open lot. When a fill reduces the open lot (partial or
    full close), the realized P&L for the reduced portion is booked into
    realized_pnl. A reversal (crossing through flat) is handled as two legs.
    """

    def __init__(self, starting_cash: Decimal = Decimal("0")) -> None:
        self._cash = starting_cash
        self._positions: dict[str, _MutablePosition] = {}
        self._marks: dict[str, Decimal] = {}
        self._sod_equity: Decimal = starting_cash
        self._sod_date: date | None = None
        self._lock = RLock()

    @property
    def lock(self) -> RLock:
        return self._lock

    def set_starting_state(
        self,
        cash: Decimal,
        positions: dict[str, Position],
        sod_equity: Decimal | None = None,
        sod_date: date | None = None,
    ) -> None:
        with self._lock:
            self._cash = cash
            self._positions = {
                sym: _MutablePosition(p.symbol, p.qty, p.avg_cost, p.realized_pnl)
                for sym, p in positions.items()
            }
            if sod_equity is not None:
                self._sod_equity = sod_equity
            if sod_date is not None:
                self._sod_date = sod_date

    def apply_fill(self, fill: Fill) -> None:
        with self._lock:
            sym = fill.symbol.upper()
            pos = self._positions.get(sym)
            signed_qty = fill.qty if fill.side is Side.BUY else -fill.qty
            if pos is None or pos.qty == 0:
                new_qty = signed_qty
                new_avg = fill.price
                if pos is None:
                    self._positions[sym] = _MutablePosition(
                        sym, new_qty, new_avg, Decimal("0")
                    )
                else:
                    pos.qty = new_qty
                    pos.avg_cost = new_avg
                self._cash -= signed_qty * fill.price
                return

            same_direction = (pos.qty > 0 and signed_qty > 0) or (
                pos.qty < 0 and signed_qty < 0
            )

            if same_direction:
                total_qty = pos.qty + signed_qty
                pos.avg_cost = (
                    pos.avg_cost * pos.qty + fill.price * signed_qty
                ) / total_qty
                pos.qty = total_qty
                self._cash -= signed_qty * fill.price
                return

            # Opposite direction: closing, fully flattening, or reversing.
            abs_pos = abs(pos.qty)
            abs_fill = abs(signed_qty)
            close_qty = min(abs_pos, abs_fill)
            # realized per share: (exit - entry) * long_sign
            long_sign = Decimal("1") if pos.qty > 0 else Decimal("-1")
            realized = (fill.price - pos.avg_cost) * close_qty * long_sign
            pos.realized_pnl += realized
            self._cash -= signed_qty * fill.price

            if abs_fill < abs_pos:
                pos.qty += signed_qty  # reduce
                # avg_cost stays the same for remaining open lot
            elif abs_fill == abs_pos:
                pos.qty = Decimal("0")
                pos.avg_cost = Decimal("0")
            else:
                # reversal: flatten, then open new lot with remainder at fill price
                remaining = signed_qty + pos.qty  # signed remainder
                pos.qty = remaining
                pos.avg_cost = fill.price

    def mark(self, prices: dict[str, Decimal]) -> None:
        with self._lock:
            for sym, price in prices.items():
                self._marks[sym.upper()] = Decimal(price)

    def ensure_sod(self, now: datetime) -> None:
        with self._lock:
            today = now.astimezone(timezone.utc).date()
            if self._sod_date != today:
                self._sod_date = today
                self._sod_equity = self._compute_equity_locked()

    def _compute_equity_locked(self) -> Decimal:
        total = self._cash
        for sym, pos in self._positions.items():
            if pos.qty == 0:
                continue
            mark = self._marks.get(sym, pos.avg_cost)
            total += mark * pos.qty
        return total

    def snapshot(self, now: datetime | None = None) -> PortfolioSnapshot:
        with self._lock:
            if now is not None:
                self.ensure_sod(now)
            return PortfolioSnapshot(
                ts=now or datetime.now(timezone.utc),
                cash=self._cash,
                positions={s: p.frozen() for s, p in self._positions.items()},
                marks=dict(self._marks),
                sod_equity=self._sod_equity,
            )

    def get_position(self, symbol: str) -> Position:
        with self._lock:
            sym = symbol.upper()
            pos = self._positions.get(sym)
            if pos is None:
                return Position(sym, Decimal("0"), Decimal("0"), Decimal("0"))
            return pos.frozen()

    def cash(self) -> Decimal:
        with self._lock:
            return self._cash

    def sod_equity(self) -> Decimal:
        with self._lock:
            return self._sod_equity
