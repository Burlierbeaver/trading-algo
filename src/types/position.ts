import { z } from "zod";

export const PositionSchema = z.object({
  symbol: z.string().min(1),
  venue: z.string().min(1),
  qty: z.number(),
  avgPrice: z.number().positive(),
  openedAtTs: z.number().int().nonnegative(),
  strategyId: z.string().min(1),
});

export type Position = z.infer<typeof PositionSchema>;

export function positionKey(symbol: string, venue: string): string {
  return `${venue}:${symbol}`;
}
