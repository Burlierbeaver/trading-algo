import type { Signal } from "../types/index.js";
import type { Unsubscribe } from "./market-source.js";

export type SignalListener = (signal: Signal) => void;

export interface SignalSource {
  onSignal(listener: SignalListener): Unsubscribe;
}
