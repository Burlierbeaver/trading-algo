import { describe, expect, it } from "vitest";

import {
  CollectingIntentSink,
  FixedNotionalSizer,
  InMemoryClock,
  InMemoryMarketData,
  InMemorySignalSource,
  MeanReversionOnSignalStrategy,
  NewsMomentumStrategy,
  StrategyEngine,
  counterIdGen,
  type Bar,
  type Signal,
  type Strategy,
} from "../src/index.js";

function bar(ts: number, symbol: string, close: number): Bar {
  return { ts, symbol, venue: "XNAS", o: close, h: close, l: close, c: close, v: 1_000_000 };
}

function signal(overrides: Partial<Signal>): Signal {
  return {
    id: overrides.id ?? "sig",
    ts: overrides.ts ?? 1,
    symbol: overrides.symbol ?? "AAPL",
    venue: overrides.venue ?? "XNAS",
    kind: overrides.kind ?? "news",
    direction: overrides.direction ?? "long",
    strength: overrides.strength ?? 0.8,
    horizonMs: overrides.horizonMs ?? 60_000,
    metadata: overrides.metadata ?? {},
  };
}

function buildBacktest(strategy: Strategy = new NewsMomentumStrategy()) {
  const clock = new InMemoryClock(0);
  const market = new InMemoryMarketData(clock);
  const signals = new InMemorySignalSource(clock);
  const sink = new CollectingIntentSink();
  const engine = new StrategyEngine({
    clock,
    market,
    signals,
    sink,
    strategy,
    sizer: new FixedNotionalSizer(10_000),
    idGen: counterIdGen(),
  });
  engine.start();
  return { clock, market, signals, sink, engine };
}

describe("StrategyEngine — news momentum backtest", () => {
  it("emits a buy intent when a strong long news signal arrives", () => {
    const { market, signals, sink } = buildBacktest();
    market.push(bar(1, "AAPL", 100));
    signals.push(signal({ ts: 2, strength: 0.9, direction: "long" }));

    expect(sink.intents).toHaveLength(1);
    const [first] = sink.intents;
    expect(first).toMatchObject({
      symbol: "AAPL",
      venue: "XNAS",
      side: "buy",
      qty: 100,
      orderType: "market",
      tif: "day",
      reason: { strategyId: "news-momentum", decision: "open" },
      stopLoss: 98,
      takeProfit: 105,
    });
    expect(first?.reason.signalId).toBe("sig");
  });

  it("ignores weak signals", () => {
    const { market, signals, sink } = buildBacktest();
    market.push(bar(1, "AAPL", 100));
    signals.push(signal({ strength: 0.3 }));
    expect(sink.intents).toHaveLength(0);
  });

  it("ignores neutral signals", () => {
    const { market, signals, sink } = buildBacktest();
    market.push(bar(1, "AAPL", 100));
    signals.push(signal({ direction: "neutral", strength: 0.9 }));
    expect(sink.intents).toHaveLength(0);
  });

  it("drops signals that arrive before any market data", () => {
    const { signals, sink } = buildBacktest();
    signals.push(signal({ strength: 0.9 }));
    expect(sink.intents).toHaveLength(0);
  });

  it("closes an opposite position before opening the new one", () => {
    const { market, signals, sink } = buildBacktest();
    market.push(bar(1, "AAPL", 100));
    signals.push(signal({ id: "s1", ts: 2, direction: "long", strength: 0.9 }));
    market.push(bar(3, "AAPL", 110));
    signals.push(signal({ id: "s2", ts: 4, direction: "short", strength: 0.9 }));

    // Expect: open long, then close long, then open short.
    expect(sink.intents.map((i) => i.reason.decision)).toEqual(["open", "close", "open"]);
    expect(sink.intents.map((i) => i.side)).toEqual(["buy", "sell", "sell"]);
  });

  it("drops malformed signals without throwing", () => {
    const { market, signals, sink } = buildBacktest();
    market.push(bar(1, "AAPL", 100));
    // @ts-expect-error intentionally malformed
    signals.push({ id: "bad", ts: 1, symbol: "A" });
    expect(sink.intents).toHaveLength(0);
  });

  it("survives a strategy that throws", () => {
    const strategy = new NewsMomentumStrategy();
    // Sabotage onSignal to throw.
    const spy = strategy as unknown as { onSignal: (...args: unknown[]) => never };
    spy.onSignal = () => {
      throw new Error("boom");
    };

    const { market, signals, sink } = buildBacktest(strategy);
    market.push(bar(1, "AAPL", 100));
    signals.push(signal({ strength: 0.9 }));
    expect(sink.intents).toHaveLength(0);
    // A second signal should still be processed without the engine being crashed.
    signals.push(signal({ id: "s2", strength: 0.9 }));
    expect(sink.intents).toHaveLength(0);
  });

  it("produces byte-equal output across runs (determinism)", () => {
    const run = () => {
      const { market, signals, sink } = buildBacktest();
      market.push(bar(1, "AAPL", 100));
      signals.push(signal({ id: "a", ts: 2, strength: 0.9 }));
      market.push(bar(3, "AAPL", 110));
      signals.push(signal({ id: "b", ts: 4, direction: "short", strength: 0.9 }));
      return JSON.stringify(sink.intents);
    };
    expect(run()).toBe(run());
  });
});

describe("StrategyEngine — mean reversion", () => {
  it("fades a strong signal in the opposite direction", () => {
    const { market, signals, sink } = buildBacktest(new MeanReversionOnSignalStrategy());
    market.push(bar(1, "AAPL", 200));
    signals.push(signal({ direction: "short", strength: 0.95 }));
    expect(sink.intents).toHaveLength(1);
    expect(sink.intents[0]).toMatchObject({
      side: "buy",
      reason: { strategyId: "mean-reversion-on-signal", decision: "open" },
    });
  });

  it("does not pyramid when already in position", () => {
    const { market, signals, sink } = buildBacktest(new MeanReversionOnSignalStrategy());
    market.push(bar(1, "AAPL", 200));
    signals.push(signal({ id: "a", direction: "short", strength: 0.95 }));
    signals.push(signal({ id: "b", direction: "short", strength: 0.95 }));
    expect(sink.intents).toHaveLength(1);
  });
});
