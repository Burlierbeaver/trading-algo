# Risk / Portfolio Manager — Design

**Component:** Risk / Portfolio Manager
**Role:** Veto layer between strategy engine and broker adapter. Enforces position caps, sector exposure, daily loss limit, and kill switch. Protects capital.
**Worktree:** `risk-management-system-architecture`
**Date:** 2026-04-12

## Goals

- Accept or reject every `TradeIntent` the strategy engine produces, deterministically and fast.
- Track portfolio state (positions, cash, realized/unrealized P&L) with enough precision to evaluate limits.
- Operate in **live**, **paper**, and **backtest** modes from a single implementation.
- Fail closed: on ambiguous state, unknown symbols, reconciliation drift, or internal error, reject and/or trip kill switch.
- Expose a small, stable interface to the rest of the trading system.

## Non-goals

- Position sizing. The strategy engine decides size; the risk manager can only veto.
- Execution logic, routing, retries. That is the broker adapter's job.
- Market data. Prices are passed in or pulled through the broker protocol.
- Strategy-level P&L attribution beyond `strategy_id` tagging on decisions.

## Public interface

```python
engine = RiskEngine(config, ledger, broker, sectors, store)

decision: Decision = engine.check(intent: TradeIntent)
# Decision is Order(intent, approved_at, ...) or Reject(intent, rule, reason)

engine.on_fill(fill: Fill)           # updates ledger
engine.mark(prices: dict[str, float]) # updates unrealized P&L
engine.kill(reason: str)              # trips kill switch
engine.status() -> RiskStatus         # halted?, reasons, equity, sod_equity, ...
```

All methods are synchronous. A background reconciler thread calls `engine.reconcile()` on a cadence; backtests call it inline.

## Architecture

```
strategy_engine  ──TradeIntent──▶  RiskEngine  ──Order──▶  broker_adapter
                                      │ ▲
                                      │ └─Fill── broker_adapter
                                      ▼
                                Ledger  (positions, cash, realized P&L)
                                      │
                                      ▼
                                SQLiteStore (ledger snapshots + audit log)

                                Reconciler ── periodic ──▶ Broker.get_positions/cash
                                                             drift > threshold ⇒ kill
```

The engine is pure glue. Rules are pure functions: `(intent, ledger_snapshot, prices, config) -> None | Reject`. The ledger is the only mutable store; everything downstream reads snapshots.

## Modules

```
src/risk_manager/
├── types.py            # TradeIntent, Order, Reject, Decision, Fill, Position, PortfolioSnapshot
├── config.py           # RiskConfig dataclass + YAML loader
├── ledger.py           # Ledger — positions, cash, realized P&L, mark-to-market
├── sectors.py          # SectorClassifier — JSON-backed symbol → sector map
├── audit.py            # Decision audit log (SQLite)
├── persistence.py      # SQLiteStore — ledger snapshots + audit
├── engine.py           # RiskEngine — orchestrates rules, owns kill switch
├── reconciler.py       # Reconciler — ledger vs broker drift check
├── brokers/
│   ├── protocol.py     # BrokerAdapter Protocol
│   └── simulated.py    # In-memory broker for backtest and tests
└── rules/
    ├── base.py         # Rule protocol
    ├── position_cap.py # per-symbol notional & % equity caps
    ├── sector_exposure.py
    ├── daily_loss.py   # realized + unrealized vs SoD equity
    └── kill_switch.py  # config flag, file flag, programmatic trip
```

## Core types

- `TradeIntent(symbol, side, qty|notional, order_type, limit_price?, strategy_id, client_order_id, ts)`
  - Exactly one of `qty` or `notional` is set.
- `Order(intent, approved_at, approval_id)` — passes through to broker.
- `Reject(intent, rule_name, reason, rejected_at)` — recorded in audit log.
- `Decision = Order | Reject`.
- `Fill(symbol, side, qty, price, ts, client_order_id)` — pushed by broker adapter.
- `Position(symbol, qty, avg_cost, realized_pnl)`.
- `PortfolioSnapshot(ts, cash, positions, equity, sod_equity)`.

## Rule semantics

All rules evaluate against a **post-trade hypothetical** snapshot. The engine computes "what would the portfolio look like if this filled at its reference price?" then asks each rule.

- **PositionCap** — `abs(post_qty * ref_price) > max_notional[symbol]` OR `abs(post_qty * ref_price) / equity > max_pct_equity[symbol]` ⇒ reject. Reference price: limit price for limit orders, last known mark for market orders.
- **SectorExposure** — sum of notional across same-sector positions post-trade; reject if > configured sector cap (% of equity). `UNKNOWN` sector has its own (tight) cap.
- **DailyLoss** — if `(equity - sod_equity) / sod_equity <= -max_daily_loss_pct` and the order increases risk (new buy or opening short), reject. Closing trades (reducing absolute qty) still allowed.
- **KillSwitch** — if tripped, reject everything. First rule evaluated (cheap, fails early).

Rules evaluate in fixed order: KillSwitch → DailyLoss → PositionCap → SectorExposure. First reject wins; reason includes rule name and specific values.

## State and persistence

- **Ledger** is the working store. Positions keyed by symbol, each with qty, avg_cost (VWAP), realized_pnl. Cash is a single `Decimal`. Start-of-day equity is captured on the first `mark()` after UTC midnight (configurable rollover).
- **SQLite** schema:
  - `positions(symbol PK, qty, avg_cost, realized_pnl, updated_at)`
  - `cash(id PK=0, amount, updated_at)`
  - `daily_marks(trade_date PK, sod_equity, recorded_at)`
  - `audit_log(id, ts, decision, rule, reason, intent_json, snapshot_json)`
  - `kill_state(id PK=0, tripped, reason, tripped_at)`
- Ledger writes are transactional: fill application + position + cash + audit in one transaction.

## Reconciliation

`Reconciler` compares `Ledger.snapshot()` to `broker.get_positions()` and `broker.get_cash()` on a configurable cadence (default 60s, tighter in live).

- Drift tolerance is per-symbol (qty) and global (cash, % of equity).
- Drift > tolerance → `engine.kill("reconciliation drift on SYM: ledger=X broker=Y")`.
- In backtest, `SimulatedBroker` exposes the ledger directly, so drift is always zero.

## Kill switch

Three triggers, all unify into a single `kill_state` row in SQLite:

1. **File flag** — existence of `<workdir>/KILL` (checked on every `check()`; one stat call, cheap). Allows ops to halt without code access.
2. **Config flag** — `config.kill_switch = true`.
3. **Programmatic** — `engine.kill(reason)` from any internal check (reconciler, daily loss alert, unhandled exception in rule evaluator).

Once tripped, the engine rejects everything until an operator clears it via `engine.clear_kill(operator_id, reason)`, which records to audit log.

## Concurrency

- `RiskEngine.check()` takes a process-level `threading.RLock` around ledger reads + rule evaluation + audit write.
- `on_fill()` and `mark()` take the same lock.
- Reconciler runs in a daemon thread with its own SQLite connection.
- Backtest mode disables the thread; reconciliation is driven by the simulation loop.

## Modes

Mode is a single enum `Mode.LIVE | Mode.PAPER | Mode.BACKTEST` in config. Differences:

| Concern           | Live            | Paper           | Backtest        |
|-------------------|-----------------|-----------------|-----------------|
| Broker adapter    | AlpacaBroker    | AlpacaBroker (paper endpoint) | SimulatedBroker |
| Reconciler thread | on              | on              | off (inline)    |
| SQLite path       | `./state/live.db` | `./state/paper.db` | in-memory or temp |
| Kill switch file  | `<workdir>/KILL` | `<workdir>/KILL` | disabled        |
| Clock             | wall-clock      | wall-clock      | injected from sim |

All other code paths are identical.

## Error handling

- Rule raises an exception → engine catches, records a `Reject("internal-error", ...)`, trips kill switch. Better to halt than to approve blindly.
- Broker connection error in reconciler → exponential backoff, after N consecutive failures trip kill.
- SQLite write failure → raise to caller, trip kill (state integrity compromised).
- Unknown symbol at check time → treated as UNKNOWN sector; position cap still applies; an optional config toggle can reject unknown symbols outright.

## Testing

- Unit tests per rule with table-driven cases for boundary conditions.
- Ledger tests with property-based tests (Hypothesis optional) for fill sequences preserving invariants (cash ≥ 0 if no margin, realized P&L monotonic in total, etc.).
- Engine integration test: scripted sequence of intents + fills + marks; assert decisions and audit log.
- Reconciler test with a broker stub that returns drifted state.
- Kill switch test: all three triggers, verify file flag picked up without restart.
- Backtest test: run a short simulated session end-to-end against `SimulatedBroker`.

## Configuration example

```yaml
mode: paper
kill_switch: false
workdir: ./state
max_daily_loss_pct: 0.02
position_caps:
  default:
    max_notional: 25000
    max_pct_equity: 0.05
  AAPL:
    max_notional: 50000
    max_pct_equity: 0.08
sector_caps:
  default: 0.25          # 25% of equity per sector
  UNKNOWN: 0.02          # 2% cap for unclassified symbols
reconciler:
  interval_seconds: 60
  qty_tolerance: 0        # exact match required
  cash_tolerance_pct: 0.001
broker:
  kind: alpaca
  key_env: ALPACA_KEY
  secret_env: ALPACA_SECRET
  base_url: https://paper-api.alpaca.markets
```

## What this does NOT own

- Order sizing, strategy decisions — strategy engine.
- Order routing, fills, cancels — broker adapter.
- Price feeds — passed in via `mark()` or fetched through the broker protocol.
- Position opening/closing logic beyond "is this risk-increasing?" — the rule only needs a directional signal, not strategy intent.
