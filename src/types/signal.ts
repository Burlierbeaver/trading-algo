import { z } from "zod";

export const SignalKindSchema = z.enum(["news", "event", "sentiment", "custom"]);
export type SignalKind = z.infer<typeof SignalKindSchema>;

export const SignalDirectionSchema = z.enum(["long", "short", "neutral"]);
export type SignalDirection = z.infer<typeof SignalDirectionSchema>;

export const SignalSchema = z.object({
  id: z.string().min(1),
  ts: z.number().int().nonnegative(),
  symbol: z.string().min(1),
  venue: z.string().min(1),
  kind: SignalKindSchema,
  direction: SignalDirectionSchema,
  strength: z.number().min(0).max(1),
  horizonMs: z.number().int().nonnegative(),
  metadata: z.record(z.unknown()).default({}),
});

export type Signal = z.infer<typeof SignalSchema>;
