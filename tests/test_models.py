from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from nlp_signal.models import EventType, LLMSignal, RawEvent, Signal


class TestRawEvent:
    def test_defaults(self):
        event = RawEvent(
            id="x",
            source="s",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            title="t",
        )
        assert event.body == ""
        assert event.metadata == {}

    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            RawEvent(
                id="x",
                source="s",
                published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                title="t",
                bogus="nope",
            )


class TestLLMSignal:
    def _valid(self, **overrides):
        base = dict(
            ticker="MSFT",
            event_type=EventType.EARNINGS_BEAT,
            score=0.6,
            magnitude=0.4,
            confidence=0.8,
            rationale="Beat and raise.",
        )
        base.update(overrides)
        return base

    def test_constructs(self):
        sig = LLMSignal(**self._valid())
        assert sig.ticker == "MSFT"
        assert sig.event_type is EventType.EARNINGS_BEAT

    @pytest.mark.parametrize("score", [-1.5, 1.5, -2.0, 10.0])
    def test_score_out_of_range(self, score):
        with pytest.raises(ValidationError):
            LLMSignal(**self._valid(score=score))

    @pytest.mark.parametrize("magnitude", [-0.1, 1.1])
    def test_magnitude_out_of_range(self, magnitude):
        with pytest.raises(ValidationError):
            LLMSignal(**self._valid(magnitude=magnitude))

    @pytest.mark.parametrize("confidence", [-0.1, 1.1])
    def test_confidence_out_of_range(self, confidence):
        with pytest.raises(ValidationError):
            LLMSignal(**self._valid(confidence=confidence))

    def test_rationale_length_cap(self):
        with pytest.raises(ValidationError):
            LLMSignal(**self._valid(rationale="x" * 501))


class TestSignal:
    def test_from_llm_uppercases_ticker(self):
        llm = LLMSignal(
            ticker="msft",
            event_type=EventType.EARNINGS_BEAT,
            score=0.6,
            magnitude=0.4,
            confidence=0.8,
            rationale="ok",
        )
        sig = Signal.from_llm(llm, source_event_id="evt-xyz")
        assert sig.ticker == "MSFT"
        assert sig.source_event_id == "evt-xyz"
        assert sig.extracted_at.tzinfo is not None

    def test_from_llm_preserves_fields(self):
        llm = LLMSignal(
            ticker="SPLK",
            event_type=EventType.MA_TARGET,
            score=0.95,
            magnitude=0.8,
            confidence=0.99,
            rationale="Cash deal at 31% premium.",
        )
        sig = Signal.from_llm(llm, source_event_id="evt-ma")
        assert sig.event_type is EventType.MA_TARGET
        assert sig.score == 0.95
        assert sig.magnitude == 0.8
        assert sig.confidence == 0.99
        assert sig.rationale == "Cash deal at 31% premium."
