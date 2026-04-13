from __future__ import annotations

from .base import RuleContext, RuleResult


class KillSwitchRule:
    name = "kill_switch"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        if ctx.kill_tripped:
            reason = ctx.kill_reason or "kill switch tripped"
            return RuleResult.reject(self.name, reason)
        return RuleResult.ok(self.name)
