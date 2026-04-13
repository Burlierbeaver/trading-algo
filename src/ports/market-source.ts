import type { Bar, Quote } from "../types/index.js";

export type BarListener = (bar: Bar) => void;
export type QuoteListener = (quote: Quote) => void;
export type Unsubscribe = () => void;

export interface MarketDataSource {
  latestBar(symbol: string, venue: string): Bar | undefined;
  latestQuote?(symbol: string, venue: string): Quote | undefined;
  onBar(listener: BarListener): Unsubscribe;
  onQuote?(listener: QuoteListener): Unsubscribe;
}
