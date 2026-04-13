import { describe, expect, it } from "vitest";

import {
  FixedFractionalSizer,
  FixedNotionalSizer,
  VolatilityTargetedSizer,
} from "../src/engine/sizer.js";

describe("FixedNotionalSizer", () => {
  it("floors usd/price", () => {
    const sizer = new FixedNotionalSizer(10_000);
    expect(sizer.size({ price: 150 })).toBe(66); // 10000/150 = 66.66
  });
  it("returns 0 at zero price", () => {
    const sizer = new FixedNotionalSizer(10_000);
    expect(sizer.size({ price: 0 })).toBe(0);
  });
  it("rejects non-positive usd", () => {
    expect(() => new FixedNotionalSizer(0)).toThrow();
    expect(() => new FixedNotionalSizer(-1)).toThrow();
  });
});

describe("FixedFractionalSizer", () => {
  it("uses fraction of equity", () => {
    const sizer = new FixedFractionalSizer(0.1, () => 100_000);
    expect(sizer.size({ price: 100 })).toBe(100); // 10% of 100k = 10k / 100 = 100
  });
  it("returns 0 when equity is 0", () => {
    const sizer = new FixedFractionalSizer(0.5, () => 0);
    expect(sizer.size({ price: 100 })).toBe(0);
  });
  it("rejects out-of-range fraction", () => {
    expect(() => new FixedFractionalSizer(0, () => 1)).toThrow();
    expect(() => new FixedFractionalSizer(1.5, () => 1)).toThrow();
  });
});

describe("VolatilityTargetedSizer", () => {
  it("uses targetVol / atr", () => {
    const sizer = new VolatilityTargetedSizer(1000, () => 2.5);
    expect(
      sizer.size({
        price: 100,
        bar: { ts: 1, symbol: "A", venue: "X", o: 1, h: 2, l: 0.5, c: 100, v: 1 },
      }),
    ).toBe(400); // 1000/2.5 = 400
  });
  it("returns 0 without a bar", () => {
    const sizer = new VolatilityTargetedSizer(1000, () => 2.5);
    expect(sizer.size({ price: 100 })).toBe(0);
  });
});
