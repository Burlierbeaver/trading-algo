import type { TradeIntent } from "../types/index.js";

export interface IntentSink {
  emit(intent: TradeIntent): void;
}
