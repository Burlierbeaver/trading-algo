from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nlp_signal.errors import ExtractionError, RefusalError
from nlp_signal.models import EventType, LLMExtraction, LLMSignal
from nlp_signal.processor import NLPSignalProcessor
from nlp_signal.prompts import SYSTEM_PROMPT


def _mock_response(parsed: LLMExtraction | None, *, stop_reason: str = "end_turn"):
    """Build a fake ParsedMessage: a list of content blocks with parsed_output on the text block."""
    text_block = SimpleNamespace(type="text", text="{}", parsed_output=parsed)
    return SimpleNamespace(content=[text_block], stop_reason=stop_reason)


def _fake_client(parsed: LLMExtraction | None, *, stop_reason: str = "end_turn"):
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.parse = AsyncMock(return_value=_mock_response(parsed, stop_reason=stop_reason))
    return client


async def test_single_ticker_extraction(sample_earnings_event):
    parsed = LLMExtraction(
        signals=[
            LLMSignal(
                ticker="MSFT",
                event_type=EventType.EARNINGS_BEAT,
                score=0.7,
                magnitude=0.5,
                confidence=0.9,
                rationale="Beat on EPS and raised guidance.",
            )
        ]
    )
    client = _fake_client(parsed)
    processor = NLPSignalProcessor(client=client)

    signals = await processor.process(sample_earnings_event)

    assert len(signals) == 1
    sig = signals[0]
    assert sig.ticker == "MSFT"
    assert sig.event_type is EventType.EARNINGS_BEAT
    assert sig.source_event_id == sample_earnings_event.id
    assert sig.score == 0.7


async def test_ma_fans_out_to_target_and_acquirer(sample_ma_event):
    parsed = LLMExtraction(
        signals=[
            LLMSignal(
                ticker="SPLK",
                event_type=EventType.MA_TARGET,
                score=0.9,
                magnitude=0.8,
                confidence=0.98,
                rationale="Target gets 31% cash premium.",
            ),
            LLMSignal(
                ticker="CSCO",
                event_type=EventType.MA_ACQUIRER,
                score=-0.1,
                magnitude=0.3,
                confidence=0.7,
                rationale="Acquirer at large cash outlay.",
            ),
        ]
    )
    client = _fake_client(parsed)
    processor = NLPSignalProcessor(client=client)

    signals = await processor.process(sample_ma_event)

    tickers = {s.ticker for s in signals}
    assert tickers == {"SPLK", "CSCO"}
    event_types = {s.event_type for s in signals}
    assert event_types == {EventType.MA_TARGET, EventType.MA_ACQUIRER}


async def test_non_market_event_returns_empty(sample_non_market_event):
    client = _fake_client(LLMExtraction(signals=[]))
    processor = NLPSignalProcessor(client=client)

    signals = await processor.process(sample_non_market_event)

    assert signals == []


async def test_refusal_raises(sample_earnings_event):
    client = _fake_client(None, stop_reason="refusal")
    processor = NLPSignalProcessor(client=client)

    with pytest.raises(RefusalError):
        await processor.process(sample_earnings_event)


async def test_missing_parsed_output_raises(sample_earnings_event):
    client = _fake_client(None, stop_reason="end_turn")
    processor = NLPSignalProcessor(client=client)

    with pytest.raises(ExtractionError):
        await processor.process(sample_earnings_event)


async def test_process_many_runs_concurrently(
    sample_earnings_event, sample_ma_event, sample_non_market_event
):
    # Different fixtures but same mock for simplicity.
    parsed = LLMExtraction(
        signals=[
            LLMSignal(
                ticker="MSFT",
                event_type=EventType.EARNINGS_BEAT,
                score=0.5,
                magnitude=0.3,
                confidence=0.8,
                rationale="ok",
            )
        ]
    )
    client = _fake_client(parsed)
    processor = NLPSignalProcessor(client=client, concurrency=5)

    batches = await processor.process_many(
        [sample_earnings_event, sample_ma_event, sample_non_market_event]
    )

    assert len(batches) == 3
    assert client.messages.parse.await_count == 3
    for signals in batches:
        assert len(signals) == 1


async def test_cache_control_set_on_system_prompt(sample_earnings_event):
    client = _fake_client(LLMExtraction(signals=[]))
    processor = NLPSignalProcessor(client=client)

    await processor.process(sample_earnings_event)

    kwargs = client.messages.parse.await_args.kwargs
    assert kwargs["model"] == "claude-sonnet-4-6"
    system = kwargs["system"]
    assert isinstance(system, list)
    assert system[0]["text"] == SYSTEM_PROMPT
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert kwargs["output_format"] is LLMExtraction


async def test_custom_model_and_max_tokens(sample_earnings_event):
    client = _fake_client(LLMExtraction(signals=[]))
    processor = NLPSignalProcessor(
        client=client, model="claude-haiku-4-5", max_tokens=512
    )

    await processor.process(sample_earnings_event)

    kwargs = client.messages.parse.await_args.kwargs
    assert kwargs["model"] == "claude-haiku-4-5"
    assert kwargs["max_tokens"] == 512
