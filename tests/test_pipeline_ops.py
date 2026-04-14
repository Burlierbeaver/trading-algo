"""Integration tests for the operational hooks wired into :class:`Pipeline`:
market-hours clock, killswitch, alerter, and audit log. These verify the
wiring inside ``pipeline.py``; the modules themselves have their own unit
tests."""

from __future__ import annotations

from datetime import datetime, timezone

from trading_algo.alerting import CollectingAlerter, Severity
from trading_algo.audit import InMemoryAuditLog, current_correlation_id
from trading_algo.fakes import FakeBroker, FakeNLP
from trading_algo.killswitch import InMemoryKillSwitch
from trading_algo.market_hours import MarketClock, Session
from trading_algo.pipeline import Pipeline


class _FrozenClock(MarketClock):
    """MarketClock stub that always reports a fixed session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def session(self, now: datetime | None = None) -> Session:
        return self._session

    def is_open(self, now: datetime | None = None, *, allow_extended: bool = False) -> bool:
        if allow_extended:
            return self._session in (Session.PRE_MARKET, Session.REGULAR, Session.AFTER_HOURS)
        return self._session is Session.REGULAR


async def test_market_closed_halts_before_nlp(raw_event, risk_engine):
    nlp = FakeNLP()
    broker = FakeBroker()
    pipeline = Pipeline(
        nlp=nlp,
        risk=risk_engine,
        broker=broker,
        clock=_FrozenClock(Session.CLOSED),
    )

    result = await pipeline.ingest(raw_event)

    assert result.halted is True
    assert result.signals == []
    assert broker.submitted == []


async def test_extended_hours_flag_allows_pre_market(raw_event, risk_engine):
    pipeline = Pipeline(
        nlp=FakeNLP(),
        risk=risk_engine,
        broker=FakeBroker(),
        clock=_FrozenClock(Session.PRE_MARKET),
        allow_extended_hours=True,
    )

    result = await pipeline.ingest(raw_event)

    assert result.halted is False
    assert result.executed  # pre-market allowed, trade went through


async def test_killswitch_tripped_blocks_execute(raw_event, risk_engine):
    alerter = CollectingAlerter()
    killswitch = InMemoryKillSwitch()
    killswitch.trip(reason="ops halt", actor="operator")
    broker = FakeBroker()

    pipeline = Pipeline(
        nlp=FakeNLP(),
        risk=risk_engine,
        broker=broker,
        killswitch=killswitch,
        alerter=alerter,
    )
    result = await pipeline.ingest(raw_event)

    assert result.halted is True
    assert result.approved  # risk approved
    assert result.executed == []  # but execute was skipped
    assert broker.submitted == []
    critical = [a for a in alerter.alerts if a.severity is Severity.CRITICAL]
    assert any(a.event == "killswitch_tripped" for a in critical)


async def test_alerter_receives_info_on_fill(raw_event, risk_engine):
    alerter = CollectingAlerter()
    pipeline = Pipeline(
        nlp=FakeNLP(), risk=risk_engine, broker=FakeBroker(), alerter=alerter
    )

    await pipeline.ingest(raw_event)

    fills = [a for a in alerter.alerts if a.event == "fill"]
    assert len(fills) == 1
    assert fills[0].severity is Severity.INFO
    assert fills[0].detail["symbol"] == "AAPL"


async def test_audit_captures_full_trace_under_one_correlation(raw_event, risk_engine):
    audit = InMemoryAuditLog()
    pipeline = Pipeline(
        nlp=FakeNLP(), risk=risk_engine, broker=FakeBroker(), audit=audit
    )

    await pipeline.ingest(raw_event)

    # Context should be cleared after ingest returns.
    assert current_correlation_id() is None

    correlation_ids = {r.correlation_id for r in audit.records}
    assert len(correlation_ids) == 1, "all stages should share one correlation id"

    stages = [r.stage for r in audit.records]
    for expected in ("raw_event", "signal", "intent", "order", "fill"):
        assert expected in stages, f"missing audit stage: {expected}"
