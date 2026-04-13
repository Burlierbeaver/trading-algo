from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class EventType(str, Enum):
    EARNINGS_BEAT = "earnings_beat"
    EARNINGS_MISS = "earnings_miss"
    GUIDANCE_RAISE = "guidance_raise"
    GUIDANCE_CUT = "guidance_cut"
    MA_TARGET = "ma_target"
    MA_ACQUIRER = "ma_acquirer"
    ANALYST_UPGRADE = "analyst_upgrade"
    ANALYST_DOWNGRADE = "analyst_downgrade"
    PRODUCT_LAUNCH = "product_launch"
    REGULATORY = "regulatory"
    LITIGATION = "litigation"
    MACRO = "macro"
    OTHER = "other"


class RawEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source: str
    published_at: datetime
    title: str
    body: str = ""
    metadata: dict = Field(default_factory=dict)


class LLMSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1, max_length=10)
    event_type: EventType
    score: float = Field(ge=-1.0, le=1.0)
    magnitude: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(max_length=500)


class LLMExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signals: list[LLMSignal] = Field(default_factory=list)


class Signal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_event_id: str
    ticker: str
    event_type: EventType
    score: float = Field(ge=-1.0, le=1.0)
    magnitude: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    extracted_at: datetime

    @classmethod
    def from_llm(cls, llm: LLMSignal, source_event_id: str) -> "Signal":
        return cls(
            source_event_id=source_event_id,
            ticker=llm.ticker.upper(),
            event_type=llm.event_type,
            score=llm.score,
            magnitude=llm.magnitude,
            confidence=llm.confidence,
            rationale=llm.rationale,
            extracted_at=datetime.now(timezone.utc),
        )
