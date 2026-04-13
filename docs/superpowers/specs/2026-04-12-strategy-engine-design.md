# Strategy Engine — Design

**Date:** 2026-04-12
**Component:** #3 of the trading-algo system
**Role:** Maps `Signal + MarketData` → `TradeIntent` (sizing, entry/exit triggers). "The alpha" — swappable.

## Goals

1. **Swappable strategies.** A strategy is a plugin implementing a narrow interface. The engine is indifferent to which strategy is loaded.
2. **Unified backtest + live.** The same `Strategy` code runs in backtest or live by injecting different `Clock`, `MarketDataSource`, and `SignalSource` adapters.
3. **Narrow, explicit contracts.** `Signal` (from NLP) and `TradeIntent` (to risk/exec) are zod-validated at boundaries.
4. **Deterministic.** Given the same ordered inputs and the same strategy, the engine produces the same intents — enables reproducible backtests.

## Non-goals

- Order execution (downstream).
- Risk limits / portfolio reconciliation (downstream — component #4).
- Persistence of state across process restarts (in-memory only; persistence is a later adapter).
- Multi-strategy combiners (interface allows running many instances in parallel, but there is no built-in combiner — risk/portfolio layer reconciles).

## Architecture

```
          +----------------+     +----------------+
SignalSrc ->                |     |                | -> IntentSink (risk / exec)
          |                 |     |                |
MarketSrc -> StrategyEngine --->  Strategy(plugin) |
          |                 |     |                |
    Clock ->                |     |                |
          +----------------+     +----------------+
                  |
                  +-> Sizer
                  +-> PositionTracker
```

- **StrategyEngine** — orchestrator. Subscribes to `SignalSource`, pulls current `MarketData` for the signal's symbol, invokes `Strategy.onSignal(ctx, signal)`, turns the strategy's `Decision` into a fully-sized `TradeIntent` via the `Sizer`, updates `PositionTracker`, and emits to `IntentSink`. Also fires `Strategy.onBar` for entry/exit triggers that don't depend on a new Signal.
- **Strategy** — user plugin. Pure-ish: reads from `StrategyContext` (clock, market, positions), returns a `Decision` (`open | close | hold | adjust`) for the symbol. No direct IO.
- **Sizer** — decides quantity/notional for a `Decision`. Strategies delegate sizing unless they override.
- **PositionTracker** — mirrors expected positions (from intents emitted) for the engine's view. Truth-of-record lives downstream.

## Data model

All models are zod schemas; TS types are inferred.

### `Signal` (input from NLP)

```ts
{
  id: string;              // ULID
  ts: number;              // epoch ms, when signal was produced
  symbol: string;          // e.g. "AAPL"
  venue: string;           // e.g. "XNAS"
  kind: "news" | "event" | "sentiment" | "custom";
  direction: "long" | "short" | "neutral";
  strength: number;        // [0, 1]
  horizonMs: number;       // how long the signal is actionable
  metadata: Record<string, unknown>; // free-form (headline, etc.)
}
```

### `Bar` / `Quote` (market data)

```ts
Bar  = { ts, symbol, venue, o, h, l, c, v }
Quote = { ts, symbol, venue, bid, ask, bidSize, askSize }
```

### `TradeIntent` (output to risk/exec)

```ts
{
  id: string;                     // ULID, deterministic per input
  ts: number;                     // engine clock
  symbol: string;
  venue: string;
  side: "buy" | "sell";
  qty: number;                    // shares/contracts
  orderType: "market" | "limit";
  limitPrice?: number;
  tif: "day" | "gtc" | "ioc";
  reason: {
    strategyId: string;
    signalId?: string;            // linkage to originating Signal
    decision: "open" | "close" | "adjust";
  };
  stopLoss?: number;              // absolute price
  takeProfit?: number;
}
```

### `Position`

```ts
{ symbol, venue, qty, avgPrice, openedAtTs, strategyId }
```

## Ports (injected adapters)

- `Clock` — `now(): number`. Backtest = historical, live = system time.
- `MarketDataSource` — `latestBar(symbol, venue): Bar | undefined`, `onBar(cb)`.
- `SignalSource` — `onSignal(cb)`.
- `IntentSink` — `emit(intent)`.

Engine is constructed with these four ports plus a `Strategy` and a `Sizer`. Backtest and live differ only in which adapters are plugged in.

## Sizers

- `FixedNotionalSizer(usd)` — `qty = floor(usd / price)`.
- `FixedFractionalSizer(fraction, equity)` — risk a fraction of equity.
- `VolatilityTargetedSizer(targetVol, atr)` — scale size by ATR.

Strategies return a `Decision` with optional explicit `qty`; otherwise the engine calls the configured sizer.

## Entry/exit triggers

Two paths:
1. **Signal-driven.** `Strategy.onSignal` returns a `Decision`.
2. **Market-driven** (for stops, trailing exits, time-based exits). `Strategy.onBar` runs on every bar; can return a `Decision` (typically `close` or `adjust`).

## Error handling

- Schema validation at every port boundary (zod `parse` — throws on malformed input; engine logs and drops the malformed event).
- Strategy callbacks wrapped in try/catch; an exception logs + drops that one callback, engine keeps running.
- Unknown symbol on signal → drop with a warning.
- No-position close → no-op.

## Testing strategy

- **Unit:** types (zod round-trip), sizer math, position tracker transitions, decision → intent translation.
- **Integration backtest:** feed a scripted sequence of bars + signals through an in-memory engine with an example strategy, assert the exact sequence of emitted intents.
- **Determinism:** run the same backtest twice, assert byte-equal output.

## Project layout

```
strategy-engine/
  package.json
  tsconfig.json
  vitest.config.ts
  src/
    index.ts               # public API
    types/
      signal.ts
      intent.ts
      market.ts
      position.ts
    ports/
      clock.ts
      market-source.ts
      signal-source.ts
      intent-sink.ts
    engine/
      strategy.ts          # Strategy + StrategyContext
      sizer.ts
      position-tracker.ts
      engine.ts            # StrategyEngine
    adapters/
      in-memory.ts         # for backtest/tests
    strategies/
      news-momentum.ts
      mean-reversion-on-signal.ts
  test/
    types.test.ts
    sizer.test.ts
    position-tracker.test.ts
    engine.backtest.test.ts
```

## Out of scope / later

- Persistence adapter for PositionTracker.
- Live adapters (WebSocket market data, message bus for signals) — pluggable later.
- Strategy hot-reload.
- Metrics/observability — add once the surrounding system exists.
