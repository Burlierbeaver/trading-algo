import { type Position, positionKey } from "../types/index.js";
import type { TradeIntent } from "../types/index.js";

/**
 * Mirrors the engine's expected positions based on emitted TradeIntents.
 * Truth-of-record lives downstream in the execution/risk layer; this is a
 * best-effort view so strategies can see what they've already committed to.
 */
export class PositionTracker {
  private readonly positions = new Map<string, Position>();

  get(symbol: string, venue: string): Position | undefined {
    return this.positions.get(positionKey(symbol, venue));
  }

  all(): Position[] {
    return [...this.positions.values()];
  }

  /** Apply an intent at `fillPrice` — mutates internal state. */
  apply(intent: TradeIntent, fillPrice: number): void {
    const key = positionKey(intent.symbol, intent.venue);
    const existing = this.positions.get(key);
    const signedDelta = intent.side === "buy" ? intent.qty : -intent.qty;

    if (!existing) {
      if (signedDelta === 0) return;
      this.positions.set(key, {
        symbol: intent.symbol,
        venue: intent.venue,
        qty: signedDelta,
        avgPrice: fillPrice,
        openedAtTs: intent.ts,
        strategyId: intent.reason.strategyId,
      });
      return;
    }

    const newQty = existing.qty + signedDelta;

    if (newQty === 0) {
      this.positions.delete(key);
      return;
    }

    // Same direction: weighted-average price.
    if (Math.sign(newQty) === Math.sign(existing.qty)) {
      const addedSameDir = Math.sign(existing.qty) === Math.sign(signedDelta);
      const avgPrice = addedSameDir
        ? (existing.avgPrice * Math.abs(existing.qty) + fillPrice * Math.abs(signedDelta)) /
          Math.abs(newQty)
        : existing.avgPrice;
      this.positions.set(key, { ...existing, qty: newQty, avgPrice });
      return;
    }

    // Position flipped direction — treat as a new position at fillPrice.
    this.positions.set(key, {
      ...existing,
      qty: newQty,
      avgPrice: fillPrice,
      openedAtTs: intent.ts,
    });
  }

  clear(): void {
    this.positions.clear();
  }
}
