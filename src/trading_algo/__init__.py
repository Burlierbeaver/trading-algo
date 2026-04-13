"""Public API for the integrated trading-algo system.

See README.md for the component map and ``Pipeline`` for the orchestrator."""

from trading_algo.backtest import BacktestResult, run_backtest
from trading_algo.bridges import (
    BrokerBridge,
    InMemoryIntentStore,
    IntentStore,
    PostgresIntentStore,
    StrategyEngineBridge,
    intent_to_order_request,
)
from trading_algo.ingestion import (
    IngestionSource,
    JSONLIngestion,
    ListIngestion,
    stdin_ingestion,
)
from trading_algo.pipeline import Pipeline, PipelineResult
from trading_algo.strategy import DefaultStrategy, Strategy, StrategyConfig

__all__ = [
    "BacktestResult",
    "BrokerBridge",
    "DefaultStrategy",
    "InMemoryIntentStore",
    "IngestionSource",
    "IntentStore",
    "JSONLIngestion",
    "ListIngestion",
    "Pipeline",
    "PipelineResult",
    "PostgresIntentStore",
    "Strategy",
    "StrategyConfig",
    "StrategyEngineBridge",
    "intent_to_order_request",
    "run_backtest",
    "stdin_ingestion",
]
