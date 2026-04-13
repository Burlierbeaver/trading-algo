import { describe, expect, it } from "vitest";

import {
  BarSchema,
  SignalSchema,
  TradeIntentSchema,
  PositionSchema,
} from "../src/types/index.js";

describe("SignalSchema", () => {
  it("accepts a valid signal", () => {
    const parsed = SignalSchema.parse({
      id: "sig-1",
      ts: 1_700_000_000_000,
      symbol: "AAPL",
      venue: "XNAS",
      kind: "news",
      direction: "long",
      strength: 0.8,
      horizonMs: 60_000,
      metadata: { headline: "earnings beat" },
    });
    expect(parsed.symbol).toBe("AAPL");
  });

  it("rejects strength out of [0,1]", () => {
    expect(() =>
      SignalSchema.parse({
        id: "sig",
        ts: 1,
        symbol: "AAPL",
        venue: "XNAS",
        kind: "news",
        direction: "long",
        strength: 1.5,
        horizonMs: 0,
      }),
    ).toThrow();
  });

  it("defaults metadata to {}", () => {
    const parsed = SignalSchema.parse({
      id: "sig",
      ts: 1,
      symbol: "AAPL",
      venue: "XNAS",
      kind: "news",
      direction: "long",
      strength: 0.5,
      horizonMs: 1,
    });
    expect(parsed.metadata).toEqual({});
  });
});

describe("BarSchema", () => {
  it("accepts a valid bar", () => {
    BarSchema.parse({ ts: 1, symbol: "A", venue: "X", o: 1, h: 2, l: 0.5, c: 1.5, v: 100 });
  });
  it("rejects non-positive prices", () => {
    expect(() =>
      BarSchema.parse({ ts: 1, symbol: "A", venue: "X", o: 0, h: 1, l: 1, c: 1, v: 1 }),
    ).toThrow();
  });
});

describe("TradeIntentSchema", () => {
  it("requires limitPrice when orderType is limit", () => {
    expect(() =>
      TradeIntentSchema.parse({
        id: "i",
        ts: 1,
        symbol: "A",
        venue: "X",
        side: "buy",
        qty: 10,
        orderType: "limit",
        tif: "day",
        reason: { strategyId: "s", decision: "open" },
      }),
    ).toThrow(/limitPrice/);
  });

  it("accepts a market order without limit price", () => {
    const parsed = TradeIntentSchema.parse({
      id: "i",
      ts: 1,
      symbol: "A",
      venue: "X",
      side: "buy",
      qty: 10,
      orderType: "market",
      tif: "day",
      reason: { strategyId: "s", decision: "open" },
    });
    expect(parsed.qty).toBe(10);
  });
});

describe("PositionSchema", () => {
  it("accepts short positions (negative qty)", () => {
    PositionSchema.parse({
      symbol: "A",
      venue: "X",
      qty: -5,
      avgPrice: 10,
      openedAtTs: 1,
      strategyId: "s",
    });
  });
});
