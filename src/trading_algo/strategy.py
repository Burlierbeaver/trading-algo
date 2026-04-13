from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from nlp_signal import Signal
from risk_manager import Side, TradeIntent
from risk_manager.types import OrderType


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    base_notional: Decimal = Decimal("1000")
    min_confidence: float = 0.5
    min_abs_score: float = 0.2
    strategy_id: str = "default-v1"


class Strategy(Protocol):
    def on_signal(self, signal: Signal) -> TradeIntent | None: ...


class DefaultStrategy:
    """Translates a Signal into a TradeIntent using magnitude × confidence
    to scale notional exposure. Filters low-confidence / low-magnitude noise."""

    def __init__(self, config: StrategyConfig | None = None) -> None:
        self._config = config or StrategyConfig()

    def on_signal(self, signal: Signal) -> TradeIntent | None:
        cfg = self._config
        if signal.confidence < cfg.min_confidence:
            return None
        if abs(signal.score) < cfg.min_abs_score:
            return None

        side = Side.BUY if signal.score > 0 else Side.SELL
        scale = Decimal(str(signal.magnitude)) * Decimal(str(signal.confidence))
        notional = (cfg.base_notional * scale).quantize(Decimal("0.01"))
        if notional <= 0:
            return None

        return TradeIntent(
            symbol=signal.ticker.upper(),
            side=side,
            order_type=OrderType.MARKET,
            client_order_id=uuid.uuid4().hex,
            strategy_id=cfg.strategy_id,
            notional=notional,
        )
