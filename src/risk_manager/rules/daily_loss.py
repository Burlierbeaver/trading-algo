from __future__ import annotations

from decimal import Decimal

from ..types import Side
from .base import RuleContext, RuleResult


class DailyLossRule:
    """Rejects risk-increasing orders once daily drawdown exceeds the limit.

    Risk-increasing orders:
      - a BUY that grows a long position or opens/increases one
      - a SELL that opens or grows a short position

    Closing orders (reducing absolute qty) are still allowed so the operator
    can flatten into the drawdown.
    """

    name = "daily_loss"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        snap = ctx.snapshot
        sod = snap.sod_equity
        if sod <= 0:
            return RuleResult.ok(self.name)
        equity = snap.equity
        drawdown_pct = (equity - sod) / sod  # negative when down
        limit = -ctx.config.max_daily_loss_pct
        if drawdown_pct > limit:
            return RuleResult.ok(self.name)

        # At or past the limit — only allow risk-reducing (closing) orders.
        current_qty = snap.positions.get(ctx.intent.symbol.upper())
        current = current_qty.qty if current_qty is not None else Decimal("0")

        if _is_risk_increasing(current, ctx.post_qty, ctx.intent.side):
            return RuleResult.reject(
                self.name,
                f"daily drawdown {drawdown_pct:.4%} exceeds limit "
                f"{limit:.4%}; risk-increasing orders rejected",
            )
        return RuleResult.ok(self.name)


def _is_risk_increasing(current: Decimal, post: Decimal, side: Side) -> bool:
    # Flat → any open increases risk.
    if current == 0 and post != 0:
        return True
    # Same-side growth increases risk.
    if current > 0 and post > current:
        return True
    if current < 0 and post < current:
        return True
    # Cross through zero into a new open position (reversal) increases risk.
    if current > 0 and post < 0:
        return True
    if current < 0 and post > 0:
        return True
    return False
