import { z } from "zod";

export const BarSchema = z.object({
  ts: z.number().int().nonnegative(),
  symbol: z.string().min(1),
  venue: z.string().min(1),
  o: z.number().positive(),
  h: z.number().positive(),
  l: z.number().positive(),
  c: z.number().positive(),
  v: z.number().nonnegative(),
});

export type Bar = z.infer<typeof BarSchema>;

export const QuoteSchema = z.object({
  ts: z.number().int().nonnegative(),
  symbol: z.string().min(1),
  venue: z.string().min(1),
  bid: z.number().positive(),
  ask: z.number().positive(),
  bidSize: z.number().nonnegative(),
  askSize: z.number().nonnegative(),
});

export type Quote = z.infer<typeof QuoteSchema>;
