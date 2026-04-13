from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Union


class Mode(str, Enum):
    LIVE = "live"
    PAPER = "paper"
    BACKTEST = "backtest"


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class TradeIntent:
    symbol: str
    side: Side
    order_type: OrderType
    client_order_id: str
    strategy_id: str = "default"
    qty: Decimal | None = None
    notional: Decimal | None = None
    limit_price: Decimal | None = None
    ts: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if (self.qty is None) == (self.notional is None):
            raise ValueError("TradeIntent requires exactly one of qty or notional")
        if self.qty is not None and self.qty <= 0:
            raise ValueError("qty must be positive")
        if self.notional is not None and self.notional <= 0:
            raise ValueError("notional must be positive")
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit orders require limit_price")


@dataclass(frozen=True, slots=True)
class Order:
    intent: TradeIntent
    approval_id: str
    approved_at: datetime = field(default_factory=_utcnow)

    @property
    def approved(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class Reject:
    intent: TradeIntent
    rule: str
    reason: str
    rejected_at: datetime = field(default_factory=_utcnow)

    @property
    def approved(self) -> bool:
        return False


Decision = Union[Order, Reject]


@dataclass(frozen=True, slots=True)
class Fill:
    symbol: str
    side: Side
    qty: Decimal
    price: Decimal
    client_order_id: str
    ts: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if self.qty <= 0:
            raise ValueError("fill qty must be positive")
        if self.price <= 0:
            raise ValueError("fill price must be positive")


@dataclass(frozen=True, slots=True)
class Position:
    symbol: str
    qty: Decimal                # signed: long > 0, short < 0
    avg_cost: Decimal           # VWAP of current open lot; Decimal("0") if flat
    realized_pnl: Decimal = Decimal("0")

    @property
    def is_long(self) -> bool:
        return self.qty > 0

    @property
    def is_short(self) -> bool:
        return self.qty < 0

    @property
    def is_flat(self) -> bool:
        return self.qty == 0


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    ts: datetime
    cash: Decimal
    positions: dict[str, Position]
    marks: dict[str, Decimal]
    sod_equity: Decimal

    @property
    def unrealized_pnl(self) -> Decimal:
        total = Decimal("0")
        for sym, pos in self.positions.items():
            if pos.is_flat:
                continue
            mark = self.marks.get(sym, pos.avg_cost)
            total += (mark - pos.avg_cost) * pos.qty
        return total

    @property
    def realized_pnl(self) -> Decimal:
        return sum((p.realized_pnl for p in self.positions.values()), Decimal("0"))

    @property
    def market_value(self) -> Decimal:
        total = Decimal("0")
        for sym, pos in self.positions.items():
            if pos.is_flat:
                continue
            mark = self.marks.get(sym, pos.avg_cost)
            total += mark * pos.qty
        return total

    @property
    def equity(self) -> Decimal:
        return self.cash + self.market_value


@dataclass(frozen=True, slots=True)
class RiskStatus:
    halted: bool
    halt_reason: str | None
    equity: Decimal
    sod_equity: Decimal
    daily_pnl_pct: Decimal
