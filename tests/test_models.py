from decimal import Decimal
from uuid import UUID

import pytest

from alpaca_broker_adapter.models import (
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
)


def test_market_order_with_qty_is_valid():
    o = OrderRequest(symbol="AAPL", side=OrderSide.BUY, qty=Decimal("10"))
    assert o.client_order_id  # auto-generated
    assert isinstance(o.client_order_id, UUID)
    assert o.order_type is OrderType.MARKET


def test_notional_order_is_valid():
    o = OrderRequest(symbol="SPY", side=OrderSide.BUY, notional=Decimal("100"))
    assert o.notional == Decimal("100")
    assert o.qty is None


def test_exactly_one_of_qty_or_notional():
    with pytest.raises(ValueError, match="exactly one of qty or notional"):
        OrderRequest(symbol="AAPL", side=OrderSide.BUY)
    with pytest.raises(ValueError, match="exactly one of qty or notional"):
        OrderRequest(symbol="AAPL", side=OrderSide.BUY, qty=Decimal("1"), notional=Decimal("10"))


def test_qty_must_be_positive():
    with pytest.raises(ValueError, match="qty must be positive"):
        OrderRequest(symbol="AAPL", side=OrderSide.BUY, qty=Decimal("0"))


def test_limit_requires_limit_price():
    with pytest.raises(ValueError, match="limit_price required"):
        OrderRequest(
            symbol="AAPL",
            side=OrderSide.BUY,
            qty=Decimal("1"),
            order_type=OrderType.LIMIT,
        )


def test_market_rejects_limit_price():
    with pytest.raises(ValueError, match="limit_price not allowed"):
        OrderRequest(
            symbol="AAPL",
            side=OrderSide.BUY,
            qty=Decimal("1"),
            limit_price=Decimal("100"),
        )


def test_terminal_statuses():
    assert OrderStatus.FILLED.is_terminal
    assert OrderStatus.CANCELED.is_terminal
    assert OrderStatus.REJECTED.is_terminal
    assert OrderStatus.EXPIRED.is_terminal
    assert not OrderStatus.SUBMITTED.is_terminal
    assert not OrderStatus.PARTIALLY_FILLED.is_terminal
    assert not OrderStatus.PENDING.is_terminal
