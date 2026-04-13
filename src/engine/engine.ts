import { ulid } from "ulid";

import type { Clock, IntentSink, MarketDataSource, SignalSource, Unsubscribe } from "../ports/index.js";
import {
  SignalSchema,
  TradeIntentSchema,
  type Bar,
  type Signal,
  type TradeIntent,
} from "../types/index.js";
import { PositionTracker } from "./position-tracker.js";
import {
  HOLD,
  type Decision,
  type DecisionAdjust,
  type DecisionClose,
  type DecisionOpen,
  type Strategy,
  type StrategyContext,
} from "./strategy.js";
import type { Sizer } from "./sizer.js";

export interface EngineLogger {
  warn(msg: string, meta?: Record<string, unknown>): void;
  error(msg: string, meta?: Record<string, unknown>): void;
}

const silentLogger: EngineLogger = {
  warn: () => {},
  error: () => {},
};

export interface StrategyEngineOptions {
  clock: Clock;
  market: MarketDataSource;
  signals: SignalSource;
  sink: IntentSink;
  strategy: Strategy;
  sizer: Sizer;
  logger?: EngineLogger;
  /**
   * Optional deterministic id generator (used for TradeIntent.id).
   * Defaults to `ulid()`. Backtest suites that want byte-equal output
   * across runs should inject a counter-based generator.
   */
  idGen?: () => string;
}

export class StrategyEngine {
  private readonly clock: Clock;
  private readonly market: MarketDataSource;
  private readonly signals: SignalSource;
  private readonly sink: IntentSink;
  private readonly strategy: Strategy;
  private readonly sizer: Sizer;
  private readonly logger: EngineLogger;
  private readonly idGen: () => string;
  private readonly tracker = new PositionTracker();
  private readonly unsubs: Unsubscribe[] = [];
  private started = false;

  constructor(opts: StrategyEngineOptions) {
    this.clock = opts.clock;
    this.market = opts.market;
    this.signals = opts.signals;
    this.sink = opts.sink;
    this.strategy = opts.strategy;
    this.sizer = opts.sizer;
    this.logger = opts.logger ?? silentLogger;
    this.idGen = opts.idGen ?? ulid;
  }

  get positions(): PositionTracker {
    return this.tracker;
  }

  start(): void {
    if (this.started) return;
    this.started = true;
    this.unsubs.push(this.signals.onSignal((s) => this.handleSignal(s)));
    this.unsubs.push(this.market.onBar((b) => this.handleBar(b)));
  }

  stop(): void {
    while (this.unsubs.length) {
      const u = this.unsubs.pop();
      try {
        u?.();
      } catch (err) {
        this.logger.warn("unsubscribe failed", { err: String(err) });
      }
    }
    this.started = false;
  }

  private ctx(): StrategyContext {
    return {
      clock: this.clock,
      market: this.market,
      position: (symbol, venue) => this.tracker.get(symbol, venue),
      allPositions: () => this.tracker.all(),
    };
  }

  private handleSignal(raw: Signal): void {
    const parsed = SignalSchema.safeParse(raw);
    if (!parsed.success) {
      this.logger.warn("dropped malformed signal", { issues: parsed.error.issues });
      return;
    }
    const signal = parsed.data;

    let decisions: Decision | Decision[];
    try {
      decisions = this.strategy.onSignal(this.ctx(), signal);
    } catch (err) {
      this.logger.error("strategy.onSignal threw", {
        strategyId: this.strategy.id,
        signalId: signal.id,
        err: String(err),
      });
      return;
    }

    this.applyDecisions(decisions, { signalId: signal.id });
  }

  private handleBar(bar: Bar): void {
    if (!this.strategy.onBar) return;

    let decisions: Decision | Decision[];
    try {
      decisions = this.strategy.onBar(this.ctx(), bar);
    } catch (err) {
      this.logger.error("strategy.onBar threw", {
        strategyId: this.strategy.id,
        err: String(err),
      });
      return;
    }

    this.applyDecisions(decisions, {});
  }

  private applyDecisions(decisions: Decision | Decision[], link: { signalId?: string }): void {
    const list = Array.isArray(decisions) ? decisions : [decisions];
    for (const d of list) {
      if (d.kind === "hold") continue;
      const intent = this.decisionToIntent(d, link);
      if (intent) this.emit(intent);
    }
  }

  private decisionToIntent(
    decision: DecisionOpen | DecisionClose | DecisionAdjust,
    link: { signalId?: string },
  ): TradeIntent | undefined {
    const { symbol, venue } = decision;
    const bar = this.market.latestBar(symbol, venue);
    if (!bar) {
      this.logger.warn("no market data — dropping decision", {
        symbol,
        venue,
        decision: decision.kind,
      });
      return undefined;
    }
    const price = bar.c;
    const ts = this.clock.now();

    if (decision.kind === "open") {
      const qty = decision.qty ?? this.sizer.size({ price, bar });
      if (!(qty > 0)) {
        this.logger.warn("open decision sized to 0 — skipping", { symbol, venue, price });
        return undefined;
      }
      return this.buildIntent({
        ts,
        symbol,
        venue,
        side: decision.side,
        qty,
        orderType: decision.orderType ?? "market",
        ...(decision.limitPrice !== undefined && { limitPrice: decision.limitPrice }),
        tif: "day",
        reason: { strategyId: this.strategy.id, decision: "open", ...link },
        ...(decision.stopLoss !== undefined && { stopLoss: decision.stopLoss }),
        ...(decision.takeProfit !== undefined && { takeProfit: decision.takeProfit }),
      });
    }

    if (decision.kind === "close") {
      const pos = this.tracker.get(symbol, venue);
      if (!pos || pos.qty === 0) {
        this.logger.warn("close on no position — no-op", { symbol, venue });
        return undefined;
      }
      const absQty = decision.qty ?? Math.abs(pos.qty);
      if (!(absQty > 0)) return undefined;
      const side = pos.qty > 0 ? "sell" : "buy";
      return this.buildIntent({
        ts,
        symbol,
        venue,
        side,
        qty: absQty,
        orderType: decision.orderType ?? "market",
        ...(decision.limitPrice !== undefined && { limitPrice: decision.limitPrice }),
        tif: "day",
        reason: { strategyId: this.strategy.id, decision: "close", ...link },
      });
    }

    // adjust — currently modeled as a no-op intent (stop/target management belongs to risk/exec).
    this.logger.warn("adjust decisions are not yet translated into intents", { symbol, venue });
    return undefined;
  }

  private buildIntent(partial: Omit<TradeIntent, "id">): TradeIntent {
    const intent: TradeIntent = { id: this.idGen(), ...partial };
    // Validate on the way out — belt and braces. Strategies can't forge bad intents.
    return TradeIntentSchema.parse(intent);
  }

  private emit(intent: TradeIntent): void {
    // Assume fill at the bar close price we sized against.
    const bar = this.market.latestBar(intent.symbol, intent.venue);
    if (bar) this.tracker.apply(intent, bar.c);
    this.sink.emit(intent);
  }
}

// Re-export helpers for convenience.
export { HOLD };
