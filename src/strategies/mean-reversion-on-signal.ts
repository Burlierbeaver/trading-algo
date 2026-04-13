import type { Signal } from "../types/index.js";
import { HOLD, type Decision, type Strategy, type StrategyContext } from "../engine/strategy.js";

export interface MeanReversionOptions {
  /** Signal strength above which we fade. Default 0.7. */
  fadeThreshold?: number;
  stopLossPct?: number;
  takeProfitPct?: number;
}

/**
 * Fades strong directional signals — bets on mean reversion after a news shock.
 * When a strong "long" signal arrives, opens a short (and vice versa).
 */
export class MeanReversionOnSignalStrategy implements Strategy {
  readonly id = "mean-reversion-on-signal";
  private readonly fadeThreshold: number;
  private readonly stopLossPct: number;
  private readonly takeProfitPct: number;

  constructor(opts: MeanReversionOptions = {}) {
    this.fadeThreshold = opts.fadeThreshold ?? 0.7;
    this.stopLossPct = opts.stopLossPct ?? 0.03;
    this.takeProfitPct = opts.takeProfitPct ?? 0.02;
  }

  onSignal(ctx: StrategyContext, signal: Signal): Decision {
    if (signal.direction === "neutral") return HOLD;
    if (signal.strength < this.fadeThreshold) return HOLD;

    const bar = ctx.market.latestBar(signal.symbol, signal.venue);
    if (!bar) return HOLD;

    const existing = ctx.position(signal.symbol, signal.venue);
    if (existing) return HOLD; // don't pyramid on fades

    const fadeLong = signal.direction === "short"; // fade a "short" signal by buying
    const price = bar.c;
    const stop = fadeLong ? price * (1 - this.stopLossPct) : price * (1 + this.stopLossPct);
    const target = fadeLong ? price * (1 + this.takeProfitPct) : price * (1 - this.takeProfitPct);

    return {
      kind: "open",
      symbol: signal.symbol,
      venue: signal.venue,
      side: fadeLong ? "buy" : "sell",
      stopLoss: round2(stop),
      takeProfit: round2(target),
    };
  }
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}
