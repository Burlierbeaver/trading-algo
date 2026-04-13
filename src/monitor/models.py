from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["info", "warning", "critical"]


class Position(BaseModel):
    symbol: str
    quantity: Decimal
    avg_price: Decimal
    market_value: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    realized_pnl: Decimal = Decimal("0")
    updated_at: datetime


class Trade(BaseModel):
    id: int
    symbol: str
    side: Literal["buy", "sell"]
    quantity: Decimal
    price: Decimal
    pnl: Decimal | None = None
    broker_order_id: str | None = None
    strategy: str | None = None
    executed_at: datetime


class PnLSnapshot(BaseModel):
    id: int | None = None
    snapshot_at: datetime
    equity: Decimal
    cash: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    daily_pnl: Decimal


class LivePnL(BaseModel):
    """Live ticker pushed by the strategy engine via Redis `pnl:live`."""

    equity: Decimal
    cash: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    daily_pnl: Decimal
    as_of: datetime


class Alert(BaseModel):
    id: int | None = None
    created_at: datetime | None = None
    severity: Severity
    source: str
    title: str
    detail: str | None = None
    acknowledged_at: datetime | None = None


class AlertEvent(BaseModel):
    """Inbound alert message on the `alerts:events` pub/sub channel."""

    severity: Severity
    source: str
    title: str
    detail: str | None = None


class EngineState(BaseModel):
    halted: bool
    last_heartbeat: datetime | None
    heartbeat_age_seconds: float | None
    stale: bool = False


class DashboardSnapshot(BaseModel):
    engine: EngineState
    live_pnl: LivePnL | None
    positions: list[Position] = Field(default_factory=list)
    recent_alerts: list[Alert] = Field(default_factory=list)
    recent_trades: list[Trade] = Field(default_factory=list)
    server_time: datetime
