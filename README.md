# trading-algo (integrated)

Combines all 8 worktrees of the trading-algo project into a single runnable
system.

## Layout

```
src/trading_algo/
├── pipeline.py          # RawEvent → Signal → TradeIntent → Order → OrderResult
├── strategy.py          # DefaultStrategy: Signal → TradeIntent
├── ingestion.py         # IngestionSource + JSONL / stdin / list implementations
├── backtest.py          # Adapter: DefaultStrategy ↔ backtester.Strategy ABC
├── fakes.py             # Offline FakeNLP + FakeBroker
├── cli.py               # trading-algo { demo | backtest | run }
└── bridges/
    ├── broker.py        # intent → OrderRequest + BrokerBridge
    └── strategy_engine.py  # Postgres IntentStore for the TS engine

tests/
├── conftest.py          # shared fixtures (raw_event, risk_engine, make_signal)
├── test_pipeline.py         # end-to-end orchestrator
├── test_strategy.py         # DefaultStrategy unit tests
├── test_ingestion.py        # JSONL + List ingestion
├── test_bridges.py          # broker converter + TS engine bridge
├── test_backtest.py         # backtester integration
└── test_components_installed.py  # every sibling import works
```

## Component coverage

| # | Worktree | How it's wired in |
|---|----------|-------------------|
| 1 | `data-ingestion-pipeline-architecture-overview` | `trading_algo.ingestion` — `JSONLIngestion`, `ListIngestion`, `stdin_ingestion` |
| 2 | `nlp-signal-processing-for-market-events` | `Pipeline` calls `NLPSignalProcessor.process` |
| 3 | `strategy-engine-trade-signal-processing` (TS) | `bridges.strategy_engine.PostgresIntentStore` + `StrategyEngineBridge` |
| 4 | `risk-management-system-architecture` | `Pipeline` calls `RiskEngine.check(intent)` |
| 5 | `alpaca-broker-adapter-order-execution-and-fill-rec` | `bridges.broker` converters + `BrokerBridge` |
| 6 | `backtester-and-paper-trading-historical-replay-val` | `trading_algo.run_backtest` |
| 7 | `fastapi-dashboard-for-live-trading-monitoring-and` | path-installed, booted via `make monitor` |
| 8 | `maddening-failing` (this worktree) | the integration itself |

## Pipeline

```
RawEvent ──▶ nlp_signal ──▶ Signal
Signal   ──▶ Strategy   ──▶ TradeIntent       (DefaultStrategy OR StrategyEngineBridge)
TradeIntent ──▶ risk_manager ──▶ Order | Reject
Order    ──▶ alpaca_broker_adapter ──▶ OrderResult
```

## Build + run

```
make install                       # venv + editable installs for all 6 Python components
make test                          # 18 tests, offline (uses fakes)
make demo                          # in-memory pipeline demo
make backtest                      # backtester harness run
make ingest FILE=events.jsonl      # JSONL ingest → pipeline
make infra-up                      # Postgres + Redis via docker compose
make init-db                       # create strategy-engine tables
make monitor                       # FastAPI dashboard
make strategy-ts                   # build the TS strategy engine
```

## Public API

```python
from trading_algo import (
    Pipeline, PipelineResult,
    DefaultStrategy, StrategyConfig, Strategy,
    BrokerBridge, intent_to_order_request,
    IngestionSource, JSONLIngestion, ListIngestion, stdin_ingestion,
    StrategyEngineBridge, IntentStore, InMemoryIntentStore, PostgresIntentStore,
    run_backtest, BacktestResult,
)
```
