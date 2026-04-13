from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Protocol

from .events import RawEvent, from_dict


class EventSource(Protocol):
    def __iter__(self) -> Iterator[RawEvent]: ...


@dataclass(slots=True)
class IterableEventSource:
    events: Iterable[RawEvent]

    def __iter__(self) -> Iterator[RawEvent]:
        return iter(self.events)


@dataclass(slots=True)
class FileEventSource:
    path: Path
    _path: Path = field(init=False)

    def __post_init__(self) -> None:
        self._path = Path(self.path)
        if not self._path.exists():
            raise FileNotFoundError(self._path)

    def __iter__(self) -> Iterator[RawEvent]:
        with self._path.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(f"{self._path}:{line_no}: invalid JSON: {e}") from e
                yield from_dict(obj)
