from __future__ import annotations

import json
from decimal import Decimal

from nlp_signal import Signal
from risk_manager import TradeIntent
from risk_manager.types import OrderType, Side

from trading_algo.bridges import (
    InMemoryIntentStore,
    StrategyEngineBridge,
    intent_to_insert_params,
    serialize_signal,
)
from tests.conftest import make_signal


def test_strategy_engine_bridge_publishes_then_pops_intent():
    def compute(sig: Signal) -> TradeIntent:
        return TradeIntent(
            symbol=sig.ticker,
            side=Side.BUY,
            order_type=OrderType.MARKET,
            client_order_id="ts-" + sig.source_event_id,
            notional=Decimal("500"),
        )

    store = InMemoryIntentStore(compute)
    bridge = StrategyEngineBridge(store)

    intent = bridge.on_signal(make_signal(ticker="AAPL", source_event_id="e1"))

    assert len(store.published) == 1
    assert intent is not None
    assert intent.symbol == "AAPL"
    assert intent.notional == Decimal("500")


def test_serialize_signal_matches_ts_wire_format():
    payload = json.loads(serialize_signal(make_signal(ticker="AAPL")))

    assert payload["ticker"] == "AAPL"
    assert payload["event_type"] == "earnings_beat"
    assert 0.0 <= payload["confidence"] <= 1.0


def test_intent_to_insert_params_shape():
    intent = TradeIntent(
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        client_order_id="cid-1",
        notional=Decimal("500"),
    )
    params = intent_to_insert_params(intent, "e1")

    assert params["symbol"] == "AAPL"
    assert params["side"] == "buy"
    assert params["notional"] == "500"
    assert params["qty"] is None
