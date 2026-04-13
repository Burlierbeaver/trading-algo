from __future__ import annotations

from decimal import Decimal
from typing import Callable
from uuid import UUID

from alpaca_broker_adapter import (
    BrokerAdapter as AlpacaBrokerAdapter,
    OrderRequest,
    OrderSide,
    OrderType as AlpacaOrderType,
    TimeInForce,
)
from risk_manager import Fill as RiskFill, Order as RiskOrder, Position, Side
from risk_manager.brokers.protocol import BrokerAdapter as RiskBrokerProtocol


def intent_to_order_request(order: RiskOrder) -> OrderRequest:
    """Map a risk-approved Order to the broker adapter's OrderRequest."""
    intent = order.intent
    side = OrderSide.BUY if intent.side is Side.BUY else OrderSide.SELL
    order_type = (
        AlpacaOrderType.MARKET if intent.order_type.value == "market" else AlpacaOrderType.LIMIT
    )
    try:
        client_id = UUID(intent.client_order_id)
    except ValueError:
        # Risk's TradeIntent uses a string id; OrderRequest requires UUID.
        # Derive a deterministic UUID so retries stay idempotent.
        import hashlib

        digest = hashlib.md5(intent.client_order_id.encode()).hexdigest()
        client_id = UUID(digest)

    return OrderRequest(
        symbol=intent.symbol,
        side=side,
        qty=intent.qty,
        notional=intent.notional,
        order_type=order_type,
        limit_price=intent.limit_price,
        time_in_force=TimeInForce.DAY,
        client_order_id=client_id,
    )


QuoteFn = Callable[[str], Decimal]
CashFn = Callable[[], Decimal]
PositionsFn = Callable[[], dict[str, Position]]


class BrokerBridge(RiskBrokerProtocol):
    """Implements the risk manager's read-only BrokerAdapter protocol on top
    of the alpaca_broker_adapter + user-provided quote/state callables.

    The downstream broker adapter exposes order execution but not mark-to-market
    quotes or portfolio totals directly — callers plug those in (typically by
    reading the same Postgres tables the adapter writes to)."""

    def __init__(
        self,
        broker: AlpacaBrokerAdapter,
        *,
        cash_fn: CashFn,
        positions_fn: PositionsFn,
        quote_fn: QuoteFn,
    ) -> None:
        self._broker = broker
        self._cash_fn = cash_fn
        self._positions_fn = positions_fn
        self._quote_fn = quote_fn

    def get_cash(self) -> Decimal:
        return self._cash_fn()

    def get_positions(self) -> dict[str, Position]:
        return self._positions_fn()

    def get_quote(self, symbol: str) -> Decimal:
        return self._quote_fn(symbol)


def broker_fill_to_risk_fill(fill, order_side: OrderSide) -> RiskFill:
    """Convert a broker-adapter Fill to the risk manager's Fill type."""
    side = Side.BUY if order_side is OrderSide.BUY else Side.SELL
    return RiskFill(
        symbol=fill.symbol,
        side=side,
        qty=fill.qty,
        price=fill.price,
        client_order_id=str(fill.broker_fill_id or fill.broker_order_id),
        ts=fill.filled_at,
    )
