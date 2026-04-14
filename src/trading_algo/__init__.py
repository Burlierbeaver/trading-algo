"""Public API for the integrated trading-algo system.

See README.md for the component map and ``Pipeline`` for the orchestrator."""

from trading_algo.alerting import (
    Alert,
    Alerter,
    CollectingAlerter,
    FanoutAlerter,
    PagerDutyAlerter,
    Severity,
    SlackAlerter,
)
from trading_algo.audit import (
    AuditLog,
    AuditRecord,
    InMemoryAuditLog,
    PostgresAuditLog,
    correlation,
    current_correlation_id,
    set_correlation_id,
)
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
from trading_algo.killswitch import (
    InMemoryKillSwitch,
    KillSwitch,
    KillSwitchState,
    PostgresKillSwitch,
)
from trading_algo.market_hours import MarketClock, Session
from trading_algo.pipeline import Pipeline, PipelineResult
from trading_algo.strategy import DefaultStrategy, Strategy, StrategyConfig

__all__ = [
    "Alert",
    "Alerter",
    "AuditLog",
    "AuditRecord",
    "BacktestResult",
    "BrokerBridge",
    "CollectingAlerter",
    "DefaultStrategy",
    "FanoutAlerter",
    "InMemoryAuditLog",
    "InMemoryIntentStore",
    "InMemoryKillSwitch",
    "IngestionSource",
    "IntentStore",
    "JSONLIngestion",
    "KillSwitch",
    "KillSwitchState",
    "ListIngestion",
    "MarketClock",
    "PagerDutyAlerter",
    "Pipeline",
    "PipelineResult",
    "PostgresAuditLog",
    "PostgresIntentStore",
    "PostgresKillSwitch",
    "Session",
    "Severity",
    "SlackAlerter",
    "Strategy",
    "StrategyConfig",
    "StrategyEngineBridge",
    "correlation",
    "current_correlation_id",
    "intent_to_order_request",
    "run_backtest",
    "set_correlation_id",
    "stdin_ingestion",
]
