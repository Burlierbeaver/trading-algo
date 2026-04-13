from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class TimeInForce(str, Enum):
    DAY = "day"
    GTC = "gtc"


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"

    @property
    def is_terminal(self) -> bool:
        return self in {
            OrderStatus.FILLED,
            OrderStatus.CANCELED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        }


class OrderRequest(BaseModel):
    symbol: str
    side: OrderSide
    qty: Optional[Decimal] = None
    notional: Optional[Decimal] = None
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[Decimal] = None
    time_in_force: TimeInForce = TimeInForce.DAY
    client_order_id: UUID = Field(default_factory=uuid4)

    @model_validator(mode="after")
    def _validate(self) -> "OrderRequest":
        if (self.qty is None) == (self.notional is None):
            raise ValueError("exactly one of qty or notional must be set")
        if self.qty is not None and self.qty <= 0:
            raise ValueError("qty must be positive")
        if self.notional is not None and self.notional <= 0:
            raise ValueError("notional must be positive")
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit_price required for limit orders")
        if self.order_type is OrderType.MARKET and self.limit_price is not None:
            raise ValueError("limit_price not allowed for market orders")
        return self


class OrderResult(BaseModel):
    client_order_id: UUID
    broker_order_id: Optional[str]
    status: OrderStatus
    submitted_at: datetime
    filled_qty: Decimal = Decimal("0")
    filled_avg_price: Optional[Decimal] = None


class Fill(BaseModel):
    broker_order_id: str
    broker_fill_id: Optional[str]
    symbol: str
    side: OrderSide
    qty: Decimal
    price: Decimal
    filled_at: datetime
