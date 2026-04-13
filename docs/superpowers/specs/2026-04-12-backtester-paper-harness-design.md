# Backtester + Paper Harness — Design

**Date:** 2026-04-12
**Status:** Approved (user directed to build full system)
**Branch:** `backtester-and-paper-trading-historical-replay-val`

## Purpose

Isolated component that replays a stream of `RawEvent`s through a strategy and
produces a P&L report. Two modes share the same code path:

- **Historical mode:** file-backed event stream, sim clock, local fill simulator.
- **Paper mode:** live event stream, real clock, selectable broker (local sim by
  default; Alpaca paper trading as opt-in end-to-end validation).

The component is intentionally isolated so strategies can be validated before
risking capital via the live broker adapter.

## Non-goals

- Distributed execution, multi-process event loops.
- HFT latency. Event dispatch is single-threaded and deterministic.
- UI. Reports are JSON; the sibling FastAPI dashboard consumes them.

## Architecture

```
  EventSource  ───►  Harness  ───►  Strategy  ───►  Orders
     (file                │                             │
      or live)            ▼                             ▼
                       Clock                        Broker
                          │                             │
                          ▼                             ▼
                      Portfolio  ◄────── Fills ────────┘
                          │
                          ▼
                      Report (JSON)
```

Each unit has one responsibility and a narrow interface:

- **`EventSource`** — iterable of `RawEvent`. File-backed for historical, live
  subscription for paper. Strategies never call this directly.
- **`Clock`** — advances in lockstep with events (`SimClock`) or wall time
  (`RealClock`). Strategies read `now()`; never use `datetime.now()` directly.
- **`Strategy`** — pure ABC. `on_start`, `on_event`, `on_fill`, `on_end`. Emits
  orders via `Context.broker.submit(...)`.
- **`Broker`** — Protocol. `LocalSimBroker` matches orders against the latest
  market event using a configurable fill model. `AlpacaPaperBroker` delegates
  to the Alpaca paper endpoint (lazy import).
- **`Portfolio`** — tracks cash, positions, realized/unrealized P&L. Updated on
  each fill and mark-to-market on each market event.
- **`Harness`** — the main loop. Owns clock, broker, portfolio. Dispatches each
  event to the strategy, drains broker fills, advances state.
- **`Report`** — post-run analytics: equity curve, max drawdown, Sharpe, win
  rate, trade log. Serializable to JSON.

## Event model

`RawEvent` is an abstract base (frozen dataclass). Concrete subclasses:

- `MarketEvent` — `QuoteEvent`, `TradeEvent`, `BarEvent`. Canonical price/size.
- `NewsEvent` — raw headline + metadata (from ingestion pipeline).
- `SignalEvent` — typed signal from NLP/strategy-engine siblings.

Strategies declare what they care about by type-dispatching in `on_event`.
The harness does not filter — it forwards every event in timestamp order.

## Fill model (LocalSimBroker)

Deterministic, configurable:

- **Market orders** — fill at next market event price plus `slippage_bps`.
- **Limit orders** — fill when a subsequent quote crosses the limit.
- **Latency** — optional N-event or M-ms delay before order becomes active.
- **Partial fills** — off by default; enableable via `FillConfig`.

## Paper mode

`RealClock` + live `EventSource` (subscription interface — concrete live
implementation lives with the data-ingestion component). Orders still route
through the broker protocol; choice of `LocalSimBroker` vs `AlpacaPaperBroker`
is a constructor argument.

## Determinism guarantees

- Historical mode is fully deterministic given (source, strategy, seed).
- Any RNG is seeded from a single entropy source surfaced in the report.
- No wall-clock reads in historical mode.

## File layout

```
src/backtester/
  events.py       # RawEvent hierarchy
  clock.py        # SimClock, RealClock
  strategy.py     # Strategy ABC, Order, Context
  portfolio.py    # Portfolio, Position
  broker.py       # Broker protocol, LocalSimBroker, AlpacaPaperBroker
  source.py       # EventSource, FileEventSource, LiveEventSource
  harness.py      # ReplayHarness
  report.py       # Report, metrics
  cli.py          # `python -m backtester.cli run ...`
tests/            # unittest-based, stdlib only
```

## Testing

- Unit tests per module (events, portfolio, broker fill logic, report metrics).
- Integration test: small JSONL fixture + toy buy-and-hold strategy →
  deterministic P&L report.
- Paper-mode adapter (`AlpacaPaperBroker`) is stubbed; real Alpaca integration
  lives in the broker-adapter sibling branch.

## Dependencies between siblings

- **Consumes:** event schema (data-ingestion), signal schema (NLP, strategy-
  engine), broker API (alpaca-broker-adapter).
- **Produces:** JSON reports (fastapi-dashboard).

Interfaces here are defined as local dataclasses/Protocols so this component
compiles and tests without the siblings being built yet.
