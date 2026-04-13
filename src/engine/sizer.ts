import type { Bar } from "../types/index.js";

export interface SizerInput {
  price: number;
  bar?: Bar;
}

export interface Sizer {
  /** Returns quantity (shares/contracts). Must return an integer >= 0. */
  size(input: SizerInput): number;
}

/** Allocate a fixed USD notional per trade. qty = floor(usd / price). */
export class FixedNotionalSizer implements Sizer {
  constructor(private readonly usd: number) {
    if (!(usd > 0)) throw new Error("FixedNotionalSizer: usd must be > 0");
  }
  size({ price }: SizerInput): number {
    if (!(price > 0)) return 0;
    return Math.floor(this.usd / price);
  }
}

/** Risk a fixed fraction of current equity per trade. */
export class FixedFractionalSizer implements Sizer {
  constructor(
    private readonly fraction: number,
    private readonly getEquity: () => number,
  ) {
    if (!(fraction > 0 && fraction <= 1)) {
      throw new Error("FixedFractionalSizer: fraction must be in (0, 1]");
    }
  }
  size({ price }: SizerInput): number {
    if (!(price > 0)) return 0;
    const equity = this.getEquity();
    if (!(equity > 0)) return 0;
    return Math.floor((equity * this.fraction) / price);
  }
}

/**
 * Target a per-trade dollar volatility. Requires an ATR (average true range) from the caller.
 * qty = floor(targetVolUsd / atr). Useful for vol-targeted strategies.
 */
export class VolatilityTargetedSizer implements Sizer {
  constructor(
    private readonly targetVolUsd: number,
    private readonly getAtr: (symbol: string, venue: string) => number,
  ) {
    if (!(targetVolUsd > 0)) throw new Error("VolatilityTargetedSizer: targetVolUsd must be > 0");
  }
  size({ bar }: SizerInput): number {
    if (!bar) return 0;
    const atr = this.getAtr(bar.symbol, bar.venue);
    if (!(atr > 0)) return 0;
    return Math.floor(this.targetVolUsd / atr);
  }
}
