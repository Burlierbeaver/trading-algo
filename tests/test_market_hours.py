"""Tests for the market-hours gating module.

We pass explicit ``datetime`` objects everywhere rather than freezing time --
keeps this test file dependency-free and deterministic across environments.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from trading_algo.market_hours import MarketClock, Session

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


@pytest.fixture(scope="module")
def clock() -> MarketClock:
    return MarketClock()


# ---------------------------------------------------------------------------
# Known open day: Wednesday 2026-04-08 (regular DST session, 09:30-16:00 ET).
# ---------------------------------------------------------------------------


def test_regular_session_at_10_et(clock: MarketClock) -> None:
    assert clock.session(datetime(2026, 4, 8, 10, 0, tzinfo=ET)) is Session.REGULAR


def test_pre_market_at_08_et(clock: MarketClock) -> None:
    assert clock.session(datetime(2026, 4, 8, 8, 0, tzinfo=ET)) is Session.PRE_MARKET


def test_after_hours_at_17_et(clock: MarketClock) -> None:
    assert (
        clock.session(datetime(2026, 4, 8, 17, 0, tzinfo=ET)) is Session.AFTER_HOURS
    )


def test_closed_before_pre_market(clock: MarketClock) -> None:
    assert clock.session(datetime(2026, 4, 8, 3, 0, tzinfo=ET)) is Session.CLOSED


def test_closed_after_after_hours(clock: MarketClock) -> None:
    assert clock.session(datetime(2026, 4, 8, 21, 0, tzinfo=ET)) is Session.CLOSED


# ---------------------------------------------------------------------------
# Weekend -- always CLOSED.
# ---------------------------------------------------------------------------


def test_weekend_saturday_is_closed(clock: MarketClock) -> None:
    # 2026-04-11 is a Saturday. Check a range of hours.
    for hour in (3, 8, 10, 13, 17, 21):
        moment = datetime(2026, 4, 11, hour, 0, tzinfo=ET)
        assert clock.session(moment) is Session.CLOSED, hour


def test_weekend_sunday_is_closed(clock: MarketClock) -> None:
    for hour in (0, 9, 12, 16, 20):
        moment = datetime(2026, 4, 12, hour, 0, tzinfo=ET)
        assert clock.session(moment) is Session.CLOSED, hour


# ---------------------------------------------------------------------------
# Early close -- Friday 2025-11-28 (day after US Thanksgiving), closes 13:00 ET.
# Spec mentioned "day before Thanksgiving"; NYSE's actual early close is the
# day after. The 13:00-close property is what matters for the test.
# ---------------------------------------------------------------------------


def test_early_close_regular_at_noon(clock: MarketClock) -> None:
    assert (
        clock.session(datetime(2025, 11, 28, 12, 0, tzinfo=ET)) is Session.REGULAR
    )


def test_early_close_closed_after_13(clock: MarketClock) -> None:
    # At 13:30 ET the regular session is over. Spec says this should be CLOSED
    # -- i.e. we do NOT flip into AFTER_HOURS just because the calendar closed
    # early. After-hours still starts at 16:00 ET.
    assert (
        clock.session(datetime(2025, 11, 28, 13, 30, tzinfo=ET)) is Session.CLOSED
    )


def test_early_close_after_hours_at_17(clock: MarketClock) -> None:
    assert (
        clock.session(datetime(2025, 11, 28, 17, 0, tzinfo=ET))
        is Session.AFTER_HOURS
    )


# ---------------------------------------------------------------------------
# is_open semantics.
# ---------------------------------------------------------------------------


def test_is_open_strict_only_true_for_regular(clock: MarketClock) -> None:
    regular = datetime(2026, 4, 8, 10, 0, tzinfo=ET)
    pre = datetime(2026, 4, 8, 8, 0, tzinfo=ET)
    after = datetime(2026, 4, 8, 17, 0, tzinfo=ET)
    closed = datetime(2026, 4, 8, 3, 0, tzinfo=ET)

    assert clock.is_open(regular) is True
    assert clock.is_open(pre) is False
    assert clock.is_open(after) is False
    assert clock.is_open(closed) is False


def test_is_open_extended_matches_union(clock: MarketClock) -> None:
    regular = datetime(2026, 4, 8, 10, 0, tzinfo=ET)
    pre = datetime(2026, 4, 8, 8, 0, tzinfo=ET)
    after = datetime(2026, 4, 8, 17, 0, tzinfo=ET)
    closed_early = datetime(2026, 4, 8, 3, 0, tzinfo=ET)
    closed_late = datetime(2026, 4, 8, 21, 0, tzinfo=ET)
    closed_weekend = datetime(2026, 4, 11, 10, 0, tzinfo=ET)

    assert clock.is_open(regular, allow_extended=True) is True
    assert clock.is_open(pre, allow_extended=True) is True
    assert clock.is_open(after, allow_extended=True) is True
    assert clock.is_open(closed_early, allow_extended=True) is False
    assert clock.is_open(closed_late, allow_extended=True) is False
    assert clock.is_open(closed_weekend, allow_extended=True) is False


# ---------------------------------------------------------------------------
# next_open / next_close.
# ---------------------------------------------------------------------------


def test_next_open_on_saturday_returns_monday(clock: MarketClock) -> None:
    # 2026-04-11 is Saturday. Monday 2026-04-13 open should be 09:30 ET.
    sat_noon = datetime(2026, 4, 11, 12, 0, tzinfo=ET)
    nxt = clock.next_open(sat_noon)
    assert nxt.tzinfo is not None
    nxt_et = nxt.astimezone(ET)
    assert nxt_et.year == 2026
    assert nxt_et.month == 4
    assert nxt_et.day == 13
    assert nxt_et.hour == 9
    assert nxt_et.minute == 30


def test_next_close_during_regular_returns_today(clock: MarketClock) -> None:
    # Wed 2026-04-08 at 10:00 ET -- close is today at 16:00 ET.
    during = datetime(2026, 4, 8, 10, 0, tzinfo=ET)
    nxt = clock.next_close(during).astimezone(ET)
    assert nxt.year == 2026 and nxt.month == 4 and nxt.day == 8
    assert nxt.hour == 16 and nxt.minute == 0


def test_next_close_after_close_returns_next_session(clock: MarketClock) -> None:
    # Wed 2026-04-08 at 17:00 ET (after-hours) -- next close is Thu 04-09 16:00 ET.
    after = datetime(2026, 4, 8, 17, 0, tzinfo=ET)
    nxt = clock.next_close(after).astimezone(ET)
    assert nxt.year == 2026 and nxt.month == 4 and nxt.day == 9
    assert nxt.hour == 16 and nxt.minute == 0


def test_next_close_on_weekend_returns_monday(clock: MarketClock) -> None:
    sat = datetime(2026, 4, 11, 12, 0, tzinfo=ET)
    nxt = clock.next_close(sat).astimezone(ET)
    assert nxt.year == 2026 and nxt.month == 4 and nxt.day == 13
    assert nxt.hour == 16


# ---------------------------------------------------------------------------
# Robustness: naive datetimes treated as UTC; no exceptions on tz edge cases.
# ---------------------------------------------------------------------------


def test_naive_datetime_treated_as_utc(clock: MarketClock) -> None:
    # 14:00 UTC on 2026-04-08 == 10:00 ET == REGULAR.
    naive = datetime(2026, 4, 8, 14, 0)
    assert clock.session(naive) is Session.REGULAR


def test_now_none_does_not_raise(clock: MarketClock) -> None:
    # Just make sure calling with None works regardless of current wall clock.
    result = clock.session(None)
    assert isinstance(result, Session)
