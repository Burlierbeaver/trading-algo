from __future__ import annotations

from decimal import Decimal

from trading_algo.strategy import DefaultStrategy, StrategyConfig
from tests.conftest import make_signal


def test_side_follows_score_sign():
    strategy = DefaultStrategy(StrategyConfig(base_notional=Decimal("500")))

    buy_intent = strategy.on_signal(make_signal(score=0.8))
    sell_intent = strategy.on_signal(make_signal(score=-0.8))

    assert buy_intent is not None and sell_intent is not None
    assert buy_intent.side.value == "buy"
    assert sell_intent.side.value == "sell"


def test_low_confidence_returns_none():
    strategy = DefaultStrategy(StrategyConfig(min_confidence=0.9))
    assert strategy.on_signal(make_signal(confidence=0.5)) is None


def test_low_score_returns_none():
    strategy = DefaultStrategy(StrategyConfig(min_abs_score=0.5))
    assert strategy.on_signal(make_signal(score=0.1)) is None


def test_notional_scales_with_magnitude_times_confidence():
    strategy = DefaultStrategy(StrategyConfig(base_notional=Decimal("1000")))

    intent = strategy.on_signal(make_signal(magnitude=0.5, confidence=0.6))

    assert intent is not None
    assert intent.notional == Decimal("300.00")  # 1000 * 0.5 * 0.6
