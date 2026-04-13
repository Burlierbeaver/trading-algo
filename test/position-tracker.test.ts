import { describe, expect, it } from "vitest";

import { PositionTracker } from "../src/engine/position-tracker.js";
import type { TradeIntent } from "../src/types/index.js";

function intent(overrides: Partial<TradeIntent>): TradeIntent {
  return {
    id: "i",
    ts: 1,
    symbol: "AAPL",
    venue: "XNAS",
    side: "buy",
    qty: 10,
    orderType: "market",
    tif: "day",
    reason: { strategyId: "s", decision: "open" },
    ...overrides,
  };
}

describe("PositionTracker", () => {
  it("opens a long", () => {
    const t = new PositionTracker();
    t.apply(intent({ side: "buy", qty: 10 }), 100);
    expect(t.get("AAPL", "XNAS")).toMatchObject({ qty: 10, avgPrice: 100 });
  });

  it("opens a short", () => {
    const t = new PositionTracker();
    t.apply(intent({ side: "sell", qty: 5 }), 50);
    expect(t.get("AAPL", "XNAS")).toMatchObject({ qty: -5, avgPrice: 50 });
  });

  it("averages price when adding to a long", () => {
    const t = new PositionTracker();
    t.apply(intent({ side: "buy", qty: 10 }), 100);
    t.apply(intent({ side: "buy", qty: 10 }), 110);
    const pos = t.get("AAPL", "XNAS")!;
    expect(pos.qty).toBe(20);
    expect(pos.avgPrice).toBe(105);
  });

  it("keeps avg price unchanged when partially closing", () => {
    const t = new PositionTracker();
    t.apply(intent({ side: "buy", qty: 10 }), 100);
    t.apply(intent({ side: "sell", qty: 4 }), 120);
    const pos = t.get("AAPL", "XNAS")!;
    expect(pos.qty).toBe(6);
    expect(pos.avgPrice).toBe(100);
  });

  it("removes position on full close", () => {
    const t = new PositionTracker();
    t.apply(intent({ side: "buy", qty: 10 }), 100);
    t.apply(intent({ side: "sell", qty: 10 }), 120);
    expect(t.get("AAPL", "XNAS")).toBeUndefined();
  });

  it("flips direction at new avg price", () => {
    const t = new PositionTracker();
    t.apply(intent({ side: "buy", qty: 10 }), 100);
    t.apply(intent({ side: "sell", qty: 15 }), 105);
    const pos = t.get("AAPL", "XNAS")!;
    expect(pos.qty).toBe(-5);
    expect(pos.avgPrice).toBe(105);
  });
});
