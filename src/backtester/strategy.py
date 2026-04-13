from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from .events import RawEvent

if TYPE_CHECKING:
    from .broker import Broker
    from .clock import Clock
    from .portfolio import Fill, Portfolio


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class TimeInForce(str, Enum):
    DAY = "day"
    GTC = "gtc"
    IOC = "ioc"


@dataclass(frozen=True, slots=True)
class Order:
    symbol: str
    side: OrderSide
    qty: float
    type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    tif: TimeInForce = TimeInForce.DAY
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    client_tag: str | None = None

    def __post_init__(self) -> None:
        if self.qty <= 0:
            raise ValueError("Order.qty must be positive")
        if self.type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit orders require limit_price")


@dataclass(slots=True)
class Context:
    clock: "Clock"
    portfolio: "Portfolio"
    broker: "Broker"


class Strategy(ABC):
    @abstractmethod
    def on_event(self, event: RawEvent, ctx: Context) -> None: ...

    def on_start(self, ctx: Context) -> None:
        return None

    def on_fill(self, fill: "Fill", ctx: Context) -> None:
        return None

    def on_end(self, ctx: Context) -> None:
        return None
