PYTHON ?= /opt/homebrew/bin/python3.13
VENV   := .venv
PY     := $(VENV)/bin/python
PIP    := $(VENV)/bin/pip

ROOT            := $(CURDIR)
SIBLINGS        := $(ROOT)/..
NLP_DIR         := $(SIBLINGS)/nlp-signal-processing-for-market-events
RISK_DIR        := $(SIBLINGS)/risk-management-system-architecture
BROKER_DIR      := $(SIBLINGS)/alpaca-broker-adapter-order-execution-and-fill-rec
BACKTESTER_DIR  := $(SIBLINGS)/backtester-and-paper-trading-historical-replay-val
MONITOR_DIR     := $(SIBLINGS)/fastapi-dashboard-for-live-trading-monitoring-and
STRATEGY_TS_DIR := $(SIBLINGS)/strategy-engine-trade-signal-processing

DB_DSN ?= postgresql://trader:trader@localhost:5432/trading

.PHONY: help venv install test demo backtest ingest infra-up infra-down init-db monitor strategy-ts clean

help:
	@echo "trading-algo — integrated pipeline"
	@echo ""
	@echo "build:"
	@echo "  install        venv + editable installs for all components"
	@echo "  clean          wipe venv + build artifacts"
	@echo ""
	@echo "run:"
	@echo "  test           run the integration tests"
	@echo "  demo           in-memory pipeline demo"
	@echo "  backtest       end-to-end backtester run"
	@echo "  ingest FILE=…  pipe JSONL RawEvents through the pipeline"
	@echo ""
	@echo "infra:"
	@echo "  infra-up       start Postgres + Redis (docker compose)"
	@echo "  infra-down     stop Postgres + Redis"
	@echo "  init-db        create strategy-engine tables"
	@echo "  monitor        boot the FastAPI dashboard (needs infra-up)"
	@echo "  strategy-ts    build the TypeScript strategy engine"

# ── build ─────────────────────────────────────────────────────────────
venv:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip

install: venv
	$(PIP) install -e "$(NLP_DIR)"
	$(PIP) install -e "$(RISK_DIR)"
	$(PIP) install -e "$(BROKER_DIR)"
	$(PIP) install -e "$(BACKTESTER_DIR)"
	$(PIP) install -e "$(MONITOR_DIR)"
	$(PIP) install -e ".[dev]"

clean:
	rm -rf $(VENV) build dist *.egg-info src/*.egg-info .pytest_cache

# ── run ───────────────────────────────────────────────────────────────
test: install
	$(VENV)/bin/pytest

demo: install
	$(VENV)/bin/trading-algo demo

backtest: install
	$(VENV)/bin/trading-algo backtest

ingest: install
	@test -n "$(FILE)" || (echo "usage: make ingest FILE=path/to/events.jsonl" && exit 2)
	$(VENV)/bin/trading-algo run --events "$(FILE)"

# ── infra ─────────────────────────────────────────────────────────────
infra-up:
	docker compose up -d

infra-down:
	docker compose down

init-db: install
	$(PY) -c "from trading_algo.bridges.strategy_engine import PostgresIntentStore; PostgresIntentStore('$(DB_DSN)').init_schema(); print('schema ok')"

monitor: install
	$(VENV)/bin/trading-monitor

strategy-ts:
	cd "$(STRATEGY_TS_DIR)" && npm install && npm run build
