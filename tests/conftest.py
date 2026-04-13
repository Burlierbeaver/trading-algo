from datetime import datetime, timezone

import pytest

from nlp_signal.models import RawEvent


@pytest.fixture
def sample_earnings_event() -> RawEvent:
    return RawEvent(
        id="evt-001",
        source="reuters",
        published_at=datetime(2026, 1, 30, 21, 5, tzinfo=timezone.utc),
        title="Microsoft beats earnings estimates on cloud strength",
        body=(
            "Microsoft Corp (MSFT) reported fiscal Q2 EPS of $3.10 vs consensus "
            "$2.92, with Azure revenue growing 29% YoY. Guidance was also raised "
            "for the March quarter."
        ),
    )


@pytest.fixture
def sample_ma_event() -> RawEvent:
    return RawEvent(
        id="evt-002",
        source="bloomberg",
        published_at=datetime(2026, 2, 14, 13, 0, tzinfo=timezone.utc),
        title="Cisco to acquire Splunk in $28B all-cash deal",
        body=(
            "Cisco Systems (CSCO) announced it will acquire Splunk (SPLK) for "
            "$157 per share in cash, a 31% premium to Splunk's last close."
        ),
    )


@pytest.fixture
def sample_non_market_event() -> RawEvent:
    return RawEvent(
        id="evt-003",
        source="twitter",
        published_at=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
        title="Weather update for the Northeast",
        body="Snowstorm expected through Thursday.",
    )
