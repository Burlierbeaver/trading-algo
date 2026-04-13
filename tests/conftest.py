from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from nlp_signal import EventType, RawEvent, Signal
from risk_manager import RiskConfig, RiskEngine
from risk_manager.types import Mode


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def raw_event() -> RawEvent:
    return RawEvent(
        id="e1",
        source="test",
        published_at=_utcnow(),
        title="Apple beats earnings",
        body="body",
    )


@pytest.fixture
def risk_engine() -> RiskEngine:
    engine = RiskEngine.from_config(RiskConfig(mode=Mode.BACKTEST))
    engine.mark({"AAPL": Decimal("150.00"), "MSFT": Decimal("400.00")})
    return engine


def make_signal(
    *,
    score: float = 0.8,
    magnitude: float = 0.7,
    confidence: float = 0.9,
    ticker: str = "AAPL",
    source_event_id: str = "e1",
) -> Signal:
    return Signal(
        source_event_id=source_event_id,
        ticker=ticker,
        event_type=EventType.EARNINGS_BEAT,
        score=score,
        magnitude=magnitude,
        confidence=confidence,
        rationale="r",
        extracted_at=_utcnow(),
    )
