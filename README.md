# @trading-algo/strategy-engine

The swappable alpha layer of the trading-algo system.

Maps `Signal + MarketData` → `TradeIntent` (sizing, entry/exit triggers).

## Install

```bash
npm install
npm run build
npm test
```

## Quick example

```ts
import {
  StrategyEngine,
  FixedNotionalSizer,
  InMemoryClock,
  InMemoryMarketData,
  InMemorySignalSource,
  CollectingIntentSink,
  NewsMomentumStrategy,
} from "@trading-algo/strategy-engine";

const clock = new InMemoryClock(0);
const market = new InMemoryMarketData();
const signals = new InMemorySignalSource();
const sink = new CollectingIntentSink();

const engine = new StrategyEngine({
  clock,
  market,
  signals,
  sink,
  strategy: new NewsMomentumStrategy(),
  sizer: new FixedNotionalSizer(10_000),
});

engine.start();

market.push({ ts: 1, symbol: "AAPL", venue: "XNAS", o: 100, h: 101, l: 99, c: 100, v: 1_000_000 });
signals.push({
  id: "sig1",
  ts: 2,
  symbol: "AAPL",
  venue: "XNAS",
  kind: "news",
  direction: "long",
  strength: 0.8,
  horizonMs: 60_000,
  metadata: {},
});

console.log(sink.intents); // [TradeIntent{ side: "buy", qty: 100, ... }]
```

See `docs/superpowers/specs/2026-04-12-strategy-engine-design.md` for the full design.
