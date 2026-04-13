from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...
    def advance_to(self, ts: datetime) -> None: ...


class SimClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(1970, 1, 1, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._now

    def advance_to(self, ts: datetime) -> None:
        if ts.tzinfo is None:
            raise ValueError("advance_to requires timezone-aware datetime")
        if ts < self._now:
            raise ValueError(f"clock would move backwards: {self._now} -> {ts}")
        self._now = ts


class RealClock:
    def now(self) -> datetime:
        return datetime.now(tz=timezone.utc)

    def advance_to(self, ts: datetime) -> None:
        return None
