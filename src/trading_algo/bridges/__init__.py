"""Bridges from this integration package to each external component worktree.

Each submodule here is the seam for one neighboring component:

- ``broker`` — alpaca_broker_adapter (component #5)
- ``strategy_engine`` — the TypeScript strategy engine (component #3),
  via a shared Postgres transport
- ``robinhood_mcp`` — Robinhood's Agentic Trading MCP server as an
  alternative broker (same OrderExecutor seam as Alpaca)
"""

from trading_algo.bridges.broker import (
    BrokerBridge,
    broker_fill_to_risk_fill,
    intent_to_order_request,
)
from trading_algo.bridges.robinhood_mcp import (
    MCPError,
    OrdersDisabled,
    RobinhoodMCPBroker,
    ToolNotFound,
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
    "MCPError",
    "OrdersDisabled",
    "PostgresIntentStore",
    "RobinhoodMCPBroker",
    "ToolNotFound",
    "STRATEGY_ENGINE_SCHEMA",
    "StrategyEngineBridge",
    "broker_fill_to_risk_fill",
    "intent_to_insert_params",
    "intent_to_order_request",
    "serialize_signal",
]
