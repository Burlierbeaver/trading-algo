from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .strategy import OrderSide


@dataclass(slots=True)
class Fill:
    order_id: str
    symbol: str
    side: OrderSide
    qty: float
    price: float
    ts: datetime
    fee: float = 0.0


@dataclass(slots=True)
class Position:
    symbol: str
    qty: float = 0.0
    avg_price: float = 0.0
    realized_pnl: float = 0.0

    def market_value(self, mark: float) -> float:
        return self.qty * mark

    def unrealized_pnl(self, mark: float) -> float:
        return (mark - self.avg_price) * self.qty


@dataclass(slots=True)
class Portfolio:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    fills: list[Fill] = field(default_factory=list)
    marks: dict[str, float] = field(default_factory=dict)

    def apply_fill(self, fill: Fill) -> None:
        pos = self.positions.setdefault(fill.symbol, Position(symbol=fill.symbol))
        signed_qty = fill.qty if fill.side is OrderSide.BUY else -fill.qty
        notional = signed_qty * fill.price

        if pos.qty == 0 or _same_sign(pos.qty, signed_qty):
            new_qty = pos.qty + signed_qty
            if new_qty != 0:
                pos.avg_price = (pos.avg_price * pos.qty + fill.price * signed_qty) / new_qty
            pos.qty = new_qty
        else:
            closing = min(abs(signed_qty), abs(pos.qty))
            direction = 1.0 if pos.qty > 0 else -1.0
            pos.realized_pnl += closing * (fill.price - pos.avg_price) * direction
            pos.qty += signed_qty
            if _same_sign(pos.qty, signed_qty) and pos.qty != 0:
                pos.avg_price = fill.price
            elif pos.qty == 0:
                pos.avg_price = 0.0

        self.cash -= notional + fill.fee
        self.marks[fill.symbol] = fill.price
        self.fills.append(fill)

    def update_mark(self, symbol: str, price: float) -> None:
        self.marks[symbol] = price

    def equity(self) -> float:
        total = self.cash
        for sym, pos in self.positions.items():
            mark = self.marks.get(sym, pos.avg_price)
            total += pos.market_value(mark)
        return total

    def realized_pnl(self) -> float:
        return sum(p.realized_pnl for p in self.positions.values())

    def unrealized_pnl(self) -> float:
        return sum(
            p.unrealized_pnl(self.marks.get(sym, p.avg_price))
            for sym, p in self.positions.items()
        )


def _same_sign(a: float, b: float) -> bool:
    return (a >= 0 and b >= 0) or (a <= 0 and b <= 0)
