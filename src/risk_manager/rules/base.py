from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from ..config import RiskConfig
from ..sectors import SectorClassifier
from ..types import PortfolioSnapshot, TradeIntent


@dataclass(frozen=True, slots=True)
class RuleContext:
    """Everything a rule needs to evaluate a single TradeIntent.

    `ref_price`: reference price for the intent — limit price for limit orders,
      last known mark for market orders; rules reject if no reference exists
      and the rule needs one.
    `post_qty`: hypothetical signed post-trade qty in the subject symbol.
    `kill_tripped`: current kill switch state (for the kill switch rule only).
    `kill_reason`: reason if tripped.
    """

    intent: TradeIntent
    snapshot: PortfolioSnapshot
    ref_price: Decimal | None
    post_qty: Decimal
    config: RiskConfig
    sectors: SectorClassifier
    kill_tripped: bool
    kill_reason: str | None


@dataclass(frozen=True, slots=True)
class RuleResult:
    """Outcome of a single rule evaluation."""

    rejected: bool
    rule: str
    reason: str | None = None

    @classmethod
    def ok(cls, rule: str) -> "RuleResult":
        return cls(False, rule, None)

    @classmethod
    def reject(cls, rule: str, reason: str) -> "RuleResult":
        return cls(True, rule, reason)


class Rule(Protocol):
    name: str

    def evaluate(self, ctx: RuleContext) -> RuleResult: ...
