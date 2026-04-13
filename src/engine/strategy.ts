import type { Bar, Position, Signal, Side } from "../types/index.js";
import type { Clock, MarketDataSource } from "../ports/index.js";

export interface StrategyContext {
  readonly clock: Clock;
  readonly market: MarketDataSource;
  position(symbol: string, venue: string): Position | undefined;
  allPositions(): Position[];
}

export interface DecisionOpen {
  kind: "open";
  symbol: string;
  venue: string;
  side: Side;
  /** Optional override — when omitted the engine's sizer decides qty. */
  qty?: number;
  orderType?: "market" | "limit";
  limitPrice?: number;
  stopLoss?: number;
  takeProfit?: number;
}

export interface DecisionClose {
  kind: "close";
  symbol: string;
  venue: string;
  /** Partial close if provided; otherwise flatten. */
  qty?: number;
  orderType?: "market" | "limit";
  limitPrice?: number;
}

export interface DecisionAdjust {
  kind: "adjust";
  symbol: string;
  venue: string;
  /** New stop/target levels; undefined means leave as-is. */
  stopLoss?: number;
  takeProfit?: number;
}

export interface DecisionHold {
  kind: "hold";
}

export type Decision = DecisionOpen | DecisionClose | DecisionAdjust | DecisionHold;

export const HOLD: DecisionHold = { kind: "hold" };

export interface Strategy {
  readonly id: string;
  /** Called when a new Signal arrives for a symbol the strategy cares about. */
  onSignal(ctx: StrategyContext, signal: Signal): Decision | Decision[];
  /** Optional: called on every bar — used for stops, trailing exits, time-based exits. */
  onBar?(ctx: StrategyContext, bar: Bar): Decision | Decision[];
}
