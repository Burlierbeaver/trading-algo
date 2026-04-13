from __future__ import annotations

from decimal import Decimal

from ..sectors import UNKNOWN_SECTOR
from .base import RuleContext, RuleResult


class SectorExposureRule:
    """Rejects if post-trade same-sector notional exceeds the sector cap
    (expressed as a fraction of equity).

    Unknown symbols are bucketed under UNKNOWN. The UNKNOWN cap is configured
    via sector_caps["UNKNOWN"]; if absent, the default sector cap applies.
    """

    name = "sector_exposure"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        if ctx.ref_price is None:
            return RuleResult.ok(self.name)  # position_cap will have rejected

        intent_symbol = ctx.intent.symbol.upper()
        intent_sector = ctx.sectors.sector_of(intent_symbol)

        if (
            ctx.config.reject_unknown_symbols
            and intent_sector == UNKNOWN_SECTOR
            and not ctx.sectors.known(intent_symbol)
        ):
            return RuleResult.reject(
                self.name, f"symbol {intent_symbol} has no sector classification"
            )

        equity = ctx.snapshot.equity
        if equity <= 0:
            return RuleResult.ok(self.name)

        post_sector_notional = Decimal("0")
        for sym, pos in ctx.snapshot.positions.items():
            if pos.qty == 0:
                continue
            if ctx.sectors.sector_of(sym) != intent_sector:
                continue
            if sym == intent_symbol:
                mark = ctx.ref_price
                qty = ctx.post_qty
            else:
                mark = ctx.snapshot.marks.get(sym, pos.avg_cost)
                qty = pos.qty
            post_sector_notional += abs(qty) * mark

        # Include the subject symbol even if it wasn't in the snapshot.
        if intent_symbol not in ctx.snapshot.positions:
            post_sector_notional += abs(ctx.post_qty) * ctx.ref_price

        cap_pct = ctx.config.sector_cap_pct_for(intent_sector)
        pct = post_sector_notional / equity
        if pct > cap_pct:
            return RuleResult.reject(
                self.name,
                f"post-trade {intent_sector} exposure {post_sector_notional:.2f} "
                f"= {pct:.4%} of equity exceeds cap {cap_pct:.4%}",
            )
        return RuleResult.ok(self.name)
