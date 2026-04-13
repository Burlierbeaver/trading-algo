"""Bridges from this integration package to each external component worktree.

Each submodule here is the seam for one neighboring component:

- ``broker`` — alpaca_broker_adapter (component #5)
- ``strategy_engine`` — the TypeScript strategy engine (component #3),
  via a shared Postgres transport
"""

from trading_algo.bridges.broker import (
    BrokerBridge,
    broker_fill_to_risk_fill,
    intent_to_order_request,
)
from trading_algo.bridges.strategy_engine import (
    STRATEGY_ENGINE_SCHEMA,
    InMemoryIntentStore,
    IntentStore,
    PostgresIntentStore,
    StrategyEngineBridge,
    intent_to_insert_params,
    serialize_signal,
)

__all__ = [
    "BrokerBridge",
    "InMemoryIntentStore",
    "IntentStore",
    "PostgresIntentStore",
    "STRATEGY_ENGINE_SCHEMA",
    "StrategyEngineBridge",
    "broker_fill_to_risk_fill",
    "intent_to_insert_params",
    "intent_to_order_request",
    "serialize_signal",
]
