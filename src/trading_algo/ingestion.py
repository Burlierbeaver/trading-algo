from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import IO, Iterable, Iterator, Protocol

from nlp_signal import RawEvent


class IngestionSource(Protocol):
    """Contract for the data ingestion component (worktree
    ``data-ingestion-pipeline-architecture-overview``, currently unimplemented).

    Produces :class:`nlp_signal.RawEvent` items that feed the rest of the
    pipeline."""

    def __iter__(self) -> Iterator[RawEvent]: ...


class ListIngestion:
    """In-memory IngestionSource — yields a fixed list of events."""

    def __init__(self, events: Iterable[RawEvent]) -> None:
        self._events = list(events)

    def __iter__(self) -> Iterator[RawEvent]:
        return iter(self._events)


class JSONLIngestion:
    """Reads newline-delimited JSON events from a file or stream. Each line
    is a JSON object matching :class:`nlp_signal.RawEvent` fields. Blank
    lines and lines starting with ``#`` are ignored."""

    def __init__(self, source: str | Path | IO[str]) -> None:
        self._source = source

    def __iter__(self) -> Iterator[RawEvent]:
        if isinstance(self._source, (str, Path)):
            with open(self._source, "r", encoding="utf-8") as f:
                yield from self._parse(f)
        else:
            yield from self._parse(self._source)

    @staticmethod
    def _parse(stream: IO[str]) -> Iterator[RawEvent]:
        for raw in stream:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            yield RawEvent.model_validate_json(line)


def stdin_ingestion() -> JSONLIngestion:
    """Convenience: JSONL ingestion reading from stdin (for CLI piping)."""
    return JSONLIngestion(sys.stdin)
