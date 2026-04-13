from __future__ import annotations

from decimal import Decimal

from .base import RuleContext, RuleResult


class PositionCapRule:
    """Rejects if post-trade notional in the subject symbol exceeds either
    the absolute cap or the percent-of-equity cap.
    """

    name = "position_cap"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        if ctx.ref_price is None:
            return RuleResult.reject(
                self.name,
                f"no reference price for {ctx.intent.symbol}; cannot size position cap",
            )
        cap = ctx.config.cap_for(ctx.intent.symbol.upper())
        post_notional = abs(ctx.post_qty) * ctx.ref_price

        if post_notional > cap.max_notional:
            return RuleResult.reject(
                self.name,
                f"post-trade notional {post_notional:.2f} > max_notional "
                f"{cap.max_notional:.2f} for {ctx.intent.symbol}",
            )

        equity = ctx.snapshot.equity
        if equity > 0:
            pct = post_notional / equity
            if pct > cap.max_pct_equity:
                return RuleResult.reject(
                    self.name,
                    f"post-trade notional {post_notional:.2f} = {pct:.4%} of equity "
                    f"exceeds cap {cap.max_pct_equity:.4%} for {ctx.intent.symbol}",
                )
        return RuleResult.ok(self.name)
