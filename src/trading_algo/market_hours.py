"""Market-hours gating.

Decides whether the pipeline should be accepting events right now based on
exchange calendar data. This is NOT the killswitch -- it only knows about
calendars/sessions.

Pre-market:   04:00-09:30 ET on an open session day
Regular:      whatever ``pandas_market_calendars`` says for the day (handles
              early closes automatically)
After-hours:  16:00-20:00 ET on an open session day
Closed:       everything else

The ``MarketClock`` API is intentionally small so the integration layer can
wrap it without caring about the calendar library underneath.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from enum import Enum
from functools import lru_cache
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_market_calendars as mcal

__all__ = ["Session", "MarketClock"]


class Session(str, Enum):
    PRE_MARKET = "pre_market"
    REGULAR = "regular"
    AFTER_HOURS = "after_hours"
    CLOSED = "closed"


# Extended-hours bookends. Regular hours come from the exchange calendar so
# early closes are honored automatically.
_PRE_MARKET_START = time(4, 0)
_REGULAR_START = time(9, 30)
_AFTER_HOURS_END = time(20, 0)


class MarketClock:
    """Market-session oracle backed by ``pandas_market_calendars``."""

    def __init__(self, calendar: str = "NYSE", tz: str = "America/New_York") -> None:
        self._calendar_name = calendar
        self._tz_name = tz
        self._tz = ZoneInfo(tz)
        self._calendar = mcal.get_calendar(calendar)

    # ------------------------------------------------------------------ helpers

    def _normalize(self, now: datetime | None) -> datetime:
        """Return ``now`` as a tz-aware datetime in ``self._tz``.

        ``None`` -> current wall clock in the configured tz. Naive inputs are
        interpreted as UTC (per the spec) before being converted.
        """
        if now is None:
            return datetime.now(tz=self._tz)
        if now.tzinfo is None:
            now = now.replace(tzinfo=ZoneInfo("UTC"))
        return now.astimezone(self._tz)

    def _schedule_for(self, day: date) -> tuple[datetime, datetime] | None:
        """Return ``(market_open, market_close)`` as local-tz datetimes, or
        ``None`` if the exchange is closed that day.
        """
        return _schedule_for(self._calendar_name, self._tz_name, day)

    def _next_schedule(self, after_day: date) -> tuple[datetime, datetime]:
        """First (market_open, market_close) strictly after ``after_day``."""
        return _next_schedule(self._calendar_name, self._tz_name, after_day)

    # --------------------------------------------------------------- public API

    def session(self, now: datetime | None = None) -> Session:
        local = self._normalize(now)
        sched = self._schedule_for(local.date())
        if sched is None:
            return Session.CLOSED

        market_open, market_close = sched
        t = local.time()

        if market_open <= local < market_close:
            return Session.REGULAR
        # Extended sessions only exist on open-session days but do not extend
        # past an early close for the purposes of AFTER_HOURS start -- we keep
        # the 16:00 ET floor. When the regular close is earlier than 16:00
        # (early close day), 13:00-16:00 is CLOSED per the spec. Treat strictly
        # on wall-clock boundaries relative to the calendar's close.
        if _PRE_MARKET_START <= t < _REGULAR_START:
            return Session.PRE_MARKET
        # After-hours: from max(market_close_time, 16:00) up to 20:00.
        after_start = max(market_close.time(), time(16, 0))
        if after_start <= t < _AFTER_HOURS_END:
            return Session.AFTER_HOURS
        return Session.CLOSED

    def is_open(
        self, now: datetime | None = None, *, allow_extended: bool = False
    ) -> bool:
        s = self.session(now)
        if allow_extended:
            return s in (Session.PRE_MARKET, Session.REGULAR, Session.AFTER_HOURS)
        return s is Session.REGULAR

    def next_open(self, now: datetime | None = None) -> datetime:
        local = self._normalize(now)
        today = self._schedule_for(local.date())
        if today is not None and local < today[0]:
            return today[0]
        return self._next_schedule(local.date())[0]

    def next_close(self, now: datetime | None = None) -> datetime:
        local = self._normalize(now)
        today = self._schedule_for(local.date())
        if today is not None and local < today[1]:
            return today[1]
        return self._next_schedule(local.date())[1]


# Module-level cached lookups so repeated calls don't re-query the calendar.


@lru_cache(maxsize=4096)
def _schedule_for(
    calendar_name: str, tz_name: str, day: date
) -> tuple[datetime, datetime] | None:
    cal = mcal.get_calendar(calendar_name)
    tz = ZoneInfo(tz_name)
    sched = cal.schedule(start_date=day, end_date=day)
    if sched.empty:
        return None
    row = sched.iloc[0]
    market_open = _to_local_datetime(row["market_open"], tz)
    market_close = _to_local_datetime(row["market_close"], tz)
    return market_open, market_close


@lru_cache(maxsize=1024)
def _next_schedule(
    calendar_name: str, tz_name: str, after_day: date
) -> tuple[datetime, datetime]:
    cal = mcal.get_calendar(calendar_name)
    tz = ZoneInfo(tz_name)
    start = after_day + timedelta(days=1)
    # Look ahead ~30 days; NYSE never closes that long. Fall back to a wider
    # window if we somehow hit a gap.
    for window in (30, 120, 400):
        end = start + timedelta(days=window)
        sched = cal.schedule(start_date=start, end_date=end)
        if not sched.empty:
            row = sched.iloc[0]
            return (
                _to_local_datetime(row["market_open"], tz),
                _to_local_datetime(row["market_close"], tz),
            )
    raise RuntimeError(
        f"No upcoming session found for calendar {calendar_name!r} after {after_day}"
    )


def _to_local_datetime(value: "pd.Timestamp", tz: ZoneInfo) -> datetime:
    """Convert a pandas UTC Timestamp into a tz-aware ``datetime`` in ``tz``."""
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert(tz).to_pydatetime()
