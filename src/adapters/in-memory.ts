import type {
  BarListener,
  Clock,
  IntentSink,
  MarketDataSource,
  QuoteListener,
  SignalListener,
  SignalSource,
  Unsubscribe,
} from "../ports/index.js";
import { positionKey, type Bar, type Quote, type Signal, type TradeIntent } from "../types/index.js";

export class InMemoryClock implements Clock {
  constructor(private current: number = 0) {}
  now(): number {
    return this.current;
  }
  set(ts: number): void {
    this.current = ts;
  }
  advance(ms: number): void {
    this.current += ms;
  }
}

export class InMemoryMarketData implements MarketDataSource {
  private readonly bars = new Map<string, Bar>();
  private readonly quotes = new Map<string, Quote>();
  private readonly barListeners = new Set<BarListener>();
  private readonly quoteListeners = new Set<QuoteListener>();
  private readonly clock: InMemoryClock | undefined;

  constructor(clock?: InMemoryClock) {
    this.clock = clock;
  }

  latestBar(symbol: string, venue: string): Bar | undefined {
    return this.bars.get(positionKey(symbol, venue));
  }

  latestQuote(symbol: string, venue: string): Quote | undefined {
    return this.quotes.get(positionKey(symbol, venue));
  }

  onBar(listener: BarListener): Unsubscribe {
    this.barListeners.add(listener);
    return () => this.barListeners.delete(listener);
  }

  onQuote(listener: QuoteListener): Unsubscribe {
    this.quoteListeners.add(listener);
    return () => this.quoteListeners.delete(listener);
  }

  push(bar: Bar): void {
    this.bars.set(positionKey(bar.symbol, bar.venue), bar);
    this.clock?.set(bar.ts);
    for (const l of this.barListeners) l(bar);
  }

  pushQuote(quote: Quote): void {
    this.quotes.set(positionKey(quote.symbol, quote.venue), quote);
    this.clock?.set(quote.ts);
    for (const l of this.quoteListeners) l(quote);
  }
}

export class InMemorySignalSource implements SignalSource {
  private readonly listeners = new Set<SignalListener>();
  private readonly clock: InMemoryClock | undefined;

  constructor(clock?: InMemoryClock) {
    this.clock = clock;
  }

  onSignal(listener: SignalListener): Unsubscribe {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  push(signal: Signal): void {
    this.clock?.set(signal.ts);
    for (const l of this.listeners) l(signal);
  }
}

export class CollectingIntentSink implements IntentSink {
  readonly intents: TradeIntent[] = [];
  emit(intent: TradeIntent): void {
    this.intents.push(intent);
  }
  clear(): void {
    this.intents.length = 0;
  }
}

/**
 * Build a deterministic counter-based id generator. Useful for backtests
 * where byte-equal output across runs is required.
 */
export function counterIdGen(prefix = "intent"): () => string {
  let n = 0;
  return () => `${prefix}-${++n}`;
}
