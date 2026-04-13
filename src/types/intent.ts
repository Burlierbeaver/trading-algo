import { z } from "zod";

export const SideSchema = z.enum(["buy", "sell"]);
export type Side = z.infer<typeof SideSchema>;

export const OrderTypeSchema = z.enum(["market", "limit"]);
export type OrderType = z.infer<typeof OrderTypeSchema>;

export const TifSchema = z.enum(["day", "gtc", "ioc"]);
export type Tif = z.infer<typeof TifSchema>;

export const DecisionKindSchema = z.enum(["open", "close", "adjust"]);
export type DecisionKind = z.infer<typeof DecisionKindSchema>;

export const TradeIntentSchema = z
  .object({
    id: z.string().min(1),
    ts: z.number().int().nonnegative(),
    symbol: z.string().min(1),
    venue: z.string().min(1),
    side: SideSchema,
    qty: z.number().positive(),
    orderType: OrderTypeSchema,
    limitPrice: z.number().positive().optional(),
    tif: TifSchema,
    reason: z.object({
      strategyId: z.string().min(1),
      signalId: z.string().optional(),
      decision: DecisionKindSchema,
    }),
    stopLoss: z.number().positive().optional(),
    takeProfit: z.number().positive().optional(),
  })
  .refine((intent) => intent.orderType !== "limit" || intent.limitPrice !== undefined, {
    message: "limitPrice is required when orderType is 'limit'",
    path: ["limitPrice"],
  });

export type TradeIntent = z.infer<typeof TradeIntentSchema>;
