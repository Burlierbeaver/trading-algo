from __future__ import annotations

import asyncio
from typing import Iterable, Optional

import anthropic

from nlp_signal.errors import ExtractionError, RefusalError
from nlp_signal.models import LLMExtraction, RawEvent, Signal
from nlp_signal.prompts import SYSTEM_PROMPT, build_user_message

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 2048
DEFAULT_CONCURRENCY = 10


class NLPSignalProcessor:
    """Extracts :class:`Signal` objects from :class:`RawEvent` inputs via Claude."""

    def __init__(
        self,
        client: Optional[anthropic.AsyncAnthropic] = None,
        *,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        concurrency: int = DEFAULT_CONCURRENCY,
    ) -> None:
        self._client = client or anthropic.AsyncAnthropic()
        self._model = model
        self._max_tokens = max_tokens
        self._semaphore = asyncio.Semaphore(concurrency)

    async def process(self, event: RawEvent) -> list[Signal]:
        async with self._semaphore:
            extraction = await self._extract(event)
        return [Signal.from_llm(s, source_event_id=event.id) for s in extraction.signals]

    async def process_many(self, events: Iterable[RawEvent]) -> list[list[Signal]]:
        return await asyncio.gather(*(self.process(e) for e in events))

    async def _extract(self, event: RawEvent) -> LLMExtraction:
        user_message = build_user_message(
            title=event.title,
            body=event.body,
            source=event.source,
            published_at=event.published_at,
        )
        response = await self._client.messages.parse(
            model=self._model,
            max_tokens=self._max_tokens,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_message}],
            output_format=LLMExtraction,
        )

        if getattr(response, "stop_reason", None) == "refusal":
            raise RefusalError(f"LLM refused to process event {event.id!r}")

        for block in response.content:
            if getattr(block, "type", None) == "text":
                parsed = getattr(block, "parsed_output", None)
                if parsed is not None:
                    return parsed

        raise ExtractionError(
            f"No parsed output returned for event {event.id!r} (stop_reason={getattr(response, 'stop_reason', None)!r})"
        )
