# Alpaca Broker Adapter — Design

**Date:** 2026-04-12
**Component:** Execution / Broker Adapter
**Repo:** `trading algo` · worktree `alpaca-broker-adapter-order-execution-and-fill-rec`

## Purpose

Isolate the Alpaca broker API from the rest of the trading system. Accept
internal `OrderRequest`s, submit them to Alpaca (paper or live), reconcile
their state via REST polling, and persist order lifecycle + fills to Postgres
so downstream components (risk, P&L, dashboard) can read ground truth from
one place.

## Interface

Upstream callers (strategy engine, risk manager) use a direct in-process call:

```python
adapter = BrokerAdapter.from_env()
result = adapter.execute_order(OrderRequest(...))
```

No message bus, no HTTP. `BrokerAdapter` is the only module allowed to touch
`alpaca-py`; replacing the broker later means swapping this module.

## Inputs / Outputs

- **Input:** `OrderRequest` (Pydantic). `symbol`, `side`, `qty` XOR `notional`,
  `order_type` (market|limit), `limit_price?`, `time_in_force` (day|gtc).
- **Output (return):** `OrderResult` — `client_order_id`, `broker_order_id`,
  `status`, `submitted_at`, aggregated `filled_qty` / `filled_avg_price` when
  reached.
- **Output (side effect):** rows in Postgres — `orders` (one per order,
  updated through its lifecycle) and `fills` (one per execution).

## Modes

Env var `ALPACA_MODE = paper | live` selects base URL + API keys.

**Paper:** no safety rails, straight-through.

**Live safety rails** (all config-driven, unset = disabled):

- `MAX_NOTIONAL_PER_ORDER` — reject if `qty × ref_price` (or `notional`) exceeds.
- `MAX_QTY_PER_ORDER` — reject if `qty` exceeds.
- `SYMBOL_WHITELIST` — comma-separated; if set, only these symbols allowed.
- `KILL_SWITCH_FILE` — path; if file exists, all live submits rejected.

A violation raises `SafetyRailViolation` and is **not** sent to Alpaca. The
attempt is logged but no `orders` row is written.

## Reconciliation

Polling-only.

1. `execute_order` submits the order, writes `orders` row with
   `status = submitted`, then polls `GET /v2/orders/{id}` with a short loop
   (bounded by `POLL_TIMEOUT_S`, default 30s) to reach a terminal state.
2. On terminal state the adapter calls the activities API
   (`GET /v2/account/activities?activity_types=FILL&order_id=...`) and inserts
   one `fills` row per execution.
3. A separate `reconcile_pending_orders()` function sweeps any `orders` still
   non-terminal (e.g., GTC limit orders that didn't fill within the submit
   timeout) and can be called on a schedule by a cron/background worker.

Idempotency: every submit generates a new `client_order_id` (UUID4) up front;
Alpaca rejects duplicates, and the value is persisted before the API call so
retries can resolve to the same row.

## Persistence

### `orders`
| col | type | notes |
|---|---|---|
| id | BIGSERIAL PK | |
| client_order_id | UUID UNIQUE NOT NULL | generated pre-submit |
| broker_order_id | TEXT UNIQUE | null until Alpaca responds |
| symbol | TEXT NOT NULL | |
| side | TEXT NOT NULL | buy \| sell |
| qty | NUMERIC | nullable if notional order |
| notional | NUMERIC | nullable if qty order |
| order_type | TEXT NOT NULL | market \| limit |
| limit_price | NUMERIC | nullable |
| time_in_force | TEXT NOT NULL | day \| gtc |
| status | TEXT NOT NULL | pending \| submitted \| partially_filled \| filled \| canceled \| rejected \| expired |
| filled_qty | NUMERIC NOT NULL DEFAULT 0 | |
| filled_avg_price | NUMERIC | |
| submitted_at | TIMESTAMPTZ NOT NULL DEFAULT NOW() | |
| terminal_at | TIMESTAMPTZ | |
| mode | TEXT NOT NULL | paper \| live |
| raw | JSONB | last Alpaca response snapshot |

### `fills`
| col | type | notes |
|---|---|---|
| id | BIGSERIAL PK | |
| broker_order_id | TEXT NOT NULL REFERENCES orders(broker_order_id) | |
| broker_fill_id | TEXT UNIQUE | Alpaca activity `id` |
| symbol | TEXT NOT NULL | |
| side | TEXT NOT NULL | |
| qty | NUMERIC NOT NULL | |
| price | NUMERIC NOT NULL | |
| filled_at | TIMESTAMPTZ NOT NULL | |
| raw | JSONB | Alpaca activity payload |

Schema is created at startup via `init_schema(conn)` running idempotent
`CREATE TABLE IF NOT EXISTS` — no migration framework for this component.

## Module layout

```
src/alpaca_broker_adapter/
  __init__.py        public API re-exports
  config.py          Settings (pydantic-settings) + env loading
  models.py          OrderRequest, OrderResult, Fill, OrderStatus
  errors.py          BrokerAdapterError + subclasses
  db.py              connection pool, init_schema, repo helpers
  schema.sql         DDL
  safety.py          live preflight checks
  client.py          AlpacaClient wrapper (paper/live switch, retries)
  adapter.py         BrokerAdapter orchestration
tests/
  conftest.py        fakes: FakeAlpacaClient, in-memory sqlite-ish repo seam
  test_models.py
  test_safety.py
  test_adapter.py
```

## Errors

- `BrokerAdapterError` — base.
- `SafetyRailViolation` — pre-submit guard failed.
- `BrokerAPIError` — Alpaca returned an error or network failed after retries.
- `ReconciliationTimeout` — polling exhausted before terminal state; the order
  row is left at last-known status and the sweeper picks it up.

## Testing

- Unit tests use `FakeAlpacaClient` implementing the same narrow protocol the
  real client exposes — no HTTP mocking.
- DB tests use a repo seam so the adapter can be tested against an in-memory
  dict store without Postgres running; a separate smoke test documents how to
  exercise against real Postgres locally.
- Safety-rail tests cover each rail independently (max notional, max qty,
  whitelist, kill switch) plus an integration test showing rails are skipped
  in paper mode.

## Out of scope

- Crypto / options / multi-leg orders (equities only).
- WebSocket streams (REST polling only by decision).
- Position / P&L computation (belongs to risk-management component).
- Daily notional caps / rate limits (can be added later as another rail).
