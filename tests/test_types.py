from __future__ import annotations

from decimal import Decimal

import pytest

from risk_manager.types import OrderType, Side, TradeIntent


def test_trade_intent_requires_qty_or_notional_not_both():
    with pytest.raises(ValueError):
        TradeIntent(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            qty=Decimal("10"),
            notional=Decimal("1000"),
            client_order_id="c1",
        )


def test_trade_intent_requires_one_of():
    with pytest.raises(ValueError):
        TradeIntent(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            client_order_id="c1",
        )


def test_limit_order_requires_limit_price():
    with pytest.raises(ValueError):
        TradeIntent(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            qty=Decimal("1"),
            client_order_id="c1",
        )


def test_positive_qty():
    with pytest.raises(ValueError):
        TradeIntent(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            qty=Decimal("-1"),
            client_order_id="c1",
        )
