# trading-algo

A modular, event-driven algorithmic trading system. Each stage of the
pipeline lives in its own branch and can be swapped without touching the
rest. `main` contains the integration that wires everything together into a
single runnable system.

```
RawEvent ──▶ NLP ──▶ Signal ──▶ Strategy ──▶ TradeIntent ──▶ Risk ──▶ Order ──▶ Broker ──▶ Fill
```

---

## Why this shape

Trading systems evolve in isolated layers — the "alpha" (strategy) gets
rewritten far more often than the risk manager or the broker integration.
Keeping each stage behind a narrow interface means you can replace one piece
without re-validating the rest. Cross-stage communication goes through
shared Postgres tables where practical, so even services in different
languages (the strategy engine is TypeScript) compose cleanly.

## Components

| Stage | Branch | What it does |
|-------|--------|--------------|
| Ingestion | [`data-ingestion-pipeline-architecture-overview`](../../tree/data-ingestion-pipeline-architecture-overview) | Raw market events from feeds, APIs, filings |
| NLP | [`nlp-signal-processing-for-market-events`](../../tree/nlp-signal-processing-for-market-events) | LLM extracts `Signal` (ticker, event type, score) from each event |
| Strategy | [`strategy-engine-trade-signal-processing`](../../tree/strategy-engine-trade-signal-processing) | `Signal` → `TradeIntent`. The swappable alpha. TypeScript. |
| Risk | [`risk-management-system-architecture`](../../tree/risk-management-system-architecture) | Position caps, sector exposure, daily loss limit, kill switch |
| Broker | [`alpaca-broker-adapter-order-execution-and-fill-rec`](../../tree/alpaca-broker-adapter-order-execution-and-fill-rec) | Submits orders to Alpaca, reconciles fills to Postgres |
| Backtester | [`backtester-and-paper-trading-historical-replay-val`](../../tree/backtester-and-paper-trading-historical-replay-val) | Historical replay + paper trading harness |
| Dashboard | [`fastapi-dashboard-for-live-trading-monitoring-and`](../../tree/fastapi-dashboard-for-live-trading-monitoring-and) | FastAPI live monitor with kill switch + alerting |
| Integration | `main` (this branch) | Glues it all into a single runnable pipeline |

## Quick start

```bash
git clone https://github.com/Burlierbeaver/trading-algo.git
cd trading-algo

make install    # venv + editable installs for every component
make test       # 18 integration tests, fully offline
make demo       # run the pipeline end-to-end with in-memory fakes
```

Output from `make demo`:

```
event=demo-1
  signals:  1
  intents:  1
  approved: 1
  rejected: 0
  executed: 1
    -> filled qty=4.2000 @ 150.00
```

## Running

| Command | What it does |
|---------|--------------|
| `make demo` | Pipeline with in-memory fakes — no API keys needed |
| `make backtest` | Historical replay through the backtester harness |
| `make ingest FILE=events.jsonl` | Pipe real JSONL RawEvents through the live pipeline |
| `make infra-up` | Start Postgres + Redis via docker compose |
| `make init-db` | Create strategy-engine tables |
| `make monitor` | Boot the FastAPI dashboard (requires infra-up) |
| `make strategy-ts` | Build the TypeScript strategy engine |
| `make clean` | Wipe venv + build artifacts |

## Architecture

```
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│  Ingestion   │──▶│  NLP Signal  │──▶│   Strategy   │
│  (RSS, APIs) │   │   (LLM)      │   │  (TS or Py)  │
└──────────────┘   └──────────────┘   └──────┬───────┘
                                             │ TradeIntent
                                             ▼
                   ┌──────────────┐   ┌──────────────┐
   ┌──────────┐    │    Risk      │◀──┤    Broker    │
   │Dashboard │◀───│   Manager    │   │   (Alpaca)   │
   │(FastAPI) │    │  (caps,kill) │   │              │
   └──────────┘    └──────┬───────┘   └──────┬───────┘
                          │ Order            │ Fill
                          ▼                  ▼
                   ┌───────────────────────────────┐
                   │        Postgres bus           │
                   │   (orders, fills, audit)      │
                   └───────────────────────────────┘
```

- Synchronous path in Python (`nlp → strategy → risk → broker`) lives in
  `src/trading_algo/pipeline.py`.
- The TypeScript strategy engine plugs in through
  `trading_algo.PostgresIntentStore` — it reads `strategy_signals` and writes
  `strategy_intents`.
- The dashboard and risk reconciler read the same Postgres state the broker
  adapter writes.

## Project layout (integration branch)

```
src/trading_algo/
├── pipeline.py          Orchestrator: RawEvent → OrderResult
├── strategy.py          DefaultStrategy: Signal → TradeIntent
├── ingestion.py         IngestionSource + JSONL / stdin / list impls
├── backtest.py          Adapter into the backtester harness
├── fakes.py             Offline FakeNLP + FakeBroker
├── cli.py               trading-algo { demo | backtest | run }
└── bridges/
    ├── broker.py        intent → OrderRequest + BrokerBridge
    └── strategy_engine.py   Postgres IntentStore for the TS engine

tests/                   18 tests covering every seam
docker-compose.yml       Postgres + Redis for the dashboard + TS bridge
Makefile                 All build / run / infra commands
```

## Public API

```python
from trading_algo import (
    Pipeline, PipelineResult,
    DefaultStrategy, Strategy, StrategyConfig,
    BrokerBridge, intent_to_order_request,
    IngestionSource, JSONLIngestion, ListIngestion, stdin_ingestion,
    StrategyEngineBridge, IntentStore, InMemoryIntentStore, PostgresIntentStore,
    run_backtest, BacktestResult,
)
```

## Requirements

- Python 3.11+ (tested on 3.13)
- Docker (for the dashboard + Postgres-backed TS bridge)
- Node 18+ (only to build the TypeScript strategy engine)
- An Anthropic API key (for the real NLP processor — fakes work without one)
- Alpaca API keys (for live or paper trading — the broker adapter has a
  simulated mode for tests)

## Contributing

Each component is maintained on its own branch. To change the risk manager,
for example, check out `risk-management-system-architecture`, make your
change there, and re-integrate into `main` by opening a PR. Tests for the
component live alongside it; the integration tests on `main` verify the
seams between components.

## License

MIT
