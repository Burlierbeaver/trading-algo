import type { Signal } from "../types/index.js";
import { HOLD, type Decision, type Strategy, type StrategyContext } from "../engine/strategy.js";

export interface NewsMomentumOptions {
  /** Minimum signal strength required to act. Default 0.5. */
  threshold?: number;
  /** Stop-loss as a fraction of entry price. Default 0.02 (2%). */
  stopLossPct?: number;
  /** Take-profit as a fraction of entry price. Default 0.05 (5%). */
  takeProfitPct?: number;
}

/**
 * Opens in the direction of a news/sentiment signal whose strength clears a
 * threshold, with a bracketed stop-loss and take-profit. If a position is
 * already open for the symbol in the opposite direction, closes first.
 */
export class NewsMomentumStrategy implements Strategy {
  readonly id = "news-momentum";
  private readonly threshold: number;
  private readonly stopLossPct: number;
  private readonly takeProfitPct: number;

  constructor(opts: NewsMomentumOptions = {}) {
    this.threshold = opts.threshold ?? 0.5;
    this.stopLossPct = opts.stopLossPct ?? 0.02;
    this.takeProfitPct = opts.takeProfitPct ?? 0.05;
  }

  onSignal(ctx: StrategyContext, signal: Signal): Decision | Decision[] {
    if (signal.kind !== "news" && signal.kind !== "sentiment") return HOLD;
    if (signal.direction === "neutral") return HOLD;
    if (signal.strength < this.threshold) return HOLD;

    const bar = ctx.market.latestBar(signal.symbol, signal.venue);
    if (!bar) return HOLD;

    const price = bar.c;
    const pos = ctx.position(signal.symbol, signal.venue);
    const wantLong = signal.direction === "long";
    const decisions: Decision[] = [];

    if (pos) {
      const alreadyAligned = (pos.qty > 0 && wantLong) || (pos.qty < 0 && !wantLong);
      if (alreadyAligned) return HOLD;
      decisions.push({ kind: "close", symbol: signal.symbol, venue: signal.venue });
    }

    const stop = wantLong ? price * (1 - this.stopLossPct) : price * (1 + this.stopLossPct);
    const target = wantLong ? price * (1 + this.takeProfitPct) : price * (1 - this.takeProfitPct);

    decisions.push({
      kind: "open",
      symbol: signal.symbol,
      venue: signal.venue,
      side: wantLong ? "buy" : "sell",
      stopLoss: round2(stop),
      takeProfit: round2(target),
    });

    return decisions;
  }
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}
