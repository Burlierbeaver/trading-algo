from __future__ import annotations

import json
from urllib.error import URLError

import pytest

from trading_algo.alerting import (
    Alert,
    CollectingAlerter,
    FanoutAlerter,
    PagerDutyAlerter,
    Severity,
    SlackAlerter,
    _rank,
)


# ---------------------------------------------------------------------------
# urlopen monkeypatch helpers
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self) -> None:
        self.status = 200

    def read(self) -> bytes:
        return b"ok"

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *a: object) -> None:
        return None


class _UrlopenSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[object, float | None]] = []

    def __call__(self, req, timeout=None):  # type: ignore[no-untyped-def]
        self.calls.append((req, timeout))
        return _FakeResponse()


def _patch_urlopen(monkeypatch, target) -> _UrlopenSpy:
    spy = _UrlopenSpy()
    # Patch at both potential import sites so we don't miss.
    monkeypatch.setattr(
        "trading_algo.alerting.urlrequest.urlopen", spy, raising=True
    )
    return spy


# ---------------------------------------------------------------------------
# Severity rank
# ---------------------------------------------------------------------------


def test_rank_ordering():
    assert _rank(Severity.CRITICAL) > _rank(Severity.WARNING) > _rank(Severity.INFO)


# ---------------------------------------------------------------------------
# CollectingAlerter
# ---------------------------------------------------------------------------


def test_collecting_alerter_records_in_order():
    c = CollectingAlerter()
    c.notify(Severity.INFO, "fill", {"symbol": "AAPL"})
    c.notify(Severity.WARNING, "risk_reject", {"reason": "limit"})
    c.notify(Severity.CRITICAL, "killswitch_tripped", {"why": "dd"})
    assert [a.event for a in c.alerts] == [
        "fill",
        "risk_reject",
        "killswitch_tripped",
    ]
    assert c.alerts[0].severity is Severity.INFO
    assert c.alerts[1].severity is Severity.WARNING
    assert c.alerts[2].severity is Severity.CRITICAL


def test_collecting_alerter_accepts_alert_object():
    c = CollectingAlerter()
    a = Alert(severity=Severity.INFO, event="fill", detail={"x": 1})
    c.notify(a)
    assert c.alerts == [a]


# ---------------------------------------------------------------------------
# SlackAlerter
# ---------------------------------------------------------------------------


def test_slack_alerter_posts_json_with_event(monkeypatch):
    spy = _patch_urlopen(monkeypatch, "slack")
    slack = SlackAlerter("https://hooks.slack.test/x")
    slack.notify(Severity.INFO, "fill", {"symbol": "AAPL", "qty": 10})

    assert len(spy.calls) == 1
    req, timeout = spy.calls[0]
    assert timeout == 5.0
    body = json.loads(req.data.decode("utf-8"))
    # The event name must appear somewhere in the serialized body.
    assert "fill" in json.dumps(body)
    assert req.get_header("Content-type") == "application/json"


def test_slack_alerter_respects_min_severity(monkeypatch):
    spy = _patch_urlopen(monkeypatch, "slack")
    slack = SlackAlerter("https://hooks.slack.test/x", min_severity=Severity.WARNING)
    slack.notify(Severity.INFO, "fill", {"symbol": "AAPL"})
    assert spy.calls == []

    slack.notify(Severity.WARNING, "risk_reject", {"reason": "limit"})
    assert len(spy.calls) == 1


def test_slack_alerter_swallows_urlerror(monkeypatch):
    def boom(req, timeout=None):  # type: ignore[no-untyped-def]
        raise URLError("no route to host")

    monkeypatch.setattr("trading_algo.alerting.urlrequest.urlopen", boom)
    slack = SlackAlerter("https://hooks.slack.test/x")
    # Must not raise.
    slack.notify(Severity.INFO, "fill", {"x": 1})


def test_slack_alerter_swallows_generic_exception(monkeypatch):
    def boom(req, timeout=None):  # type: ignore[no-untyped-def]
        raise TimeoutError("slow")

    monkeypatch.setattr("trading_algo.alerting.urlrequest.urlopen", boom)
    slack = SlackAlerter("https://hooks.slack.test/x")
    slack.notify(Severity.CRITICAL, "killswitch_tripped", {"why": "dd"})


# ---------------------------------------------------------------------------
# PagerDutyAlerter
# ---------------------------------------------------------------------------


def test_pagerduty_payload_shape(monkeypatch):
    spy = _patch_urlopen(monkeypatch, "pd")
    pd = PagerDutyAlerter("routing-key-123")
    pd.notify(Severity.CRITICAL, "killswitch_tripped", {"why": "drawdown"})

    assert len(spy.calls) == 1
    req, _timeout = spy.calls[0]
    body = json.loads(req.data.decode("utf-8"))
    assert body["routing_key"] == "routing-key-123"
    assert body["event_action"] == "trigger"
    assert "dedup_key" in body and body["dedup_key"]
    assert body["payload"]["severity"] == "critical"
    assert body["payload"]["custom_details"] == {"why": "drawdown"}


def test_pagerduty_skips_below_min_severity(monkeypatch):
    spy = _patch_urlopen(monkeypatch, "pd")
    pd = PagerDutyAlerter("rk")  # defaults to WARNING
    pd.notify(Severity.INFO, "fill", {"symbol": "AAPL"})
    assert spy.calls == []

    pd.notify(Severity.WARNING, "risk_reject", {"reason": "limit"})
    assert len(spy.calls) == 1


def test_pagerduty_swallows_urlerror(monkeypatch):
    def boom(req, timeout=None):  # type: ignore[no-untyped-def]
        raise URLError("dns fail")

    monkeypatch.setattr("trading_algo.alerting.urlrequest.urlopen", boom)
    pd = PagerDutyAlerter("rk")
    pd.notify(Severity.CRITICAL, "killswitch_tripped", {"why": "dd"})


# ---------------------------------------------------------------------------
# FanoutAlerter
# ---------------------------------------------------------------------------


class _FlakyAlerter:
    def __init__(self) -> None:
        self.alerts: list[Alert] = []

    def notify(self, alert):  # type: ignore[no-untyped-def]
        raise RuntimeError("child blew up")


def test_fanout_dispatches_to_all_children():
    a, b, c = CollectingAlerter(), CollectingAlerter(), CollectingAlerter()
    fan = FanoutAlerter([a, b, c])
    fan.notify(Severity.WARNING, "risk_reject", {"reason": "limit"})

    for child in (a, b, c):
        assert len(child.alerts) == 1
        assert child.alerts[0].event == "risk_reject"
        assert child.alerts[0].severity is Severity.WARNING


def test_fanout_isolates_child_failures():
    a, c = CollectingAlerter(), CollectingAlerter()
    flaky = _FlakyAlerter()
    fan = FanoutAlerter([a, flaky, c])
    # Must not raise.
    fan.notify(Severity.CRITICAL, "killswitch_tripped", {"why": "dd"})
    assert len(a.alerts) == 1
    assert len(c.alerts) == 1


def test_fanout_with_alert_object():
    a, b = CollectingAlerter(), CollectingAlerter()
    fan = FanoutAlerter([a, b])
    alert = Alert(severity=Severity.INFO, event="fill", detail={"x": 1})
    fan.notify(alert)
    assert a.alerts[0] is alert or a.alerts[0] == alert
    assert b.alerts[0] is alert or b.alerts[0] == alert
