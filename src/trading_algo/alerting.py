"""Severity-routed alerting fan-out layer.

Thin dispatch: the pipeline calls ``alerter.notify(...)`` and moves on.
HTTP failures are logged and swallowed — Slack being down must never stop
the trading pipeline.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, Union
from urllib import request as urlrequest
from urllib.error import URLError

__all__ = [
    "Alert",
    "Alerter",
    "CollectingAlerter",
    "FanoutAlerter",
    "PagerDutyAlerter",
    "Severity",
    "SlackAlerter",
]

_log = logging.getLogger(__name__)


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


_SEVERITY_ORDER: dict[Severity, int] = {
    Severity.INFO: 0,
    Severity.WARNING: 1,
    Severity.CRITICAL: 2,
}


def _rank(severity: Severity) -> int:
    """Module-private severity rank. CRITICAL > WARNING > INFO."""
    return _SEVERITY_ORDER[Severity(severity)]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Alert:
    severity: Severity
    event: str
    detail: dict
    ts: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        # Normalize severity so callers may pass the string form.
        if not isinstance(self.severity, Severity):
            self.severity = Severity(self.severity)


class Alerter(Protocol):
    def notify(self, alert: Alert) -> None: ...


def _coerce_alert(
    arg1: Union[Alert, Severity, str],
    event: str | None = None,
    detail: dict | None = None,
) -> Alert:
    """Accept either ``notify(alert)`` or ``notify(severity, event, detail)``."""
    if isinstance(arg1, Alert):
        return arg1
    if event is None:
        raise TypeError("notify requires either an Alert or (severity, event, detail)")
    return Alert(
        severity=Severity(arg1),
        event=event,
        detail=dict(detail) if detail is not None else {},
    )


class CollectingAlerter:
    """Test double — records alerts in-memory. Implements Alerter."""

    alerts: list[Alert]

    def __init__(self) -> None:
        self.alerts = []

    def notify(
        self,
        alert: Union[Alert, Severity, str],
        event: str | None = None,
        detail: dict | None = None,
    ) -> None:
        self.alerts.append(_coerce_alert(alert, event, detail))


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    return str(obj)


class SlackAlerter:
    """POST to a Slack incoming-webhook URL. Formats as a short text block."""

    def __init__(
        self,
        webhook_url: str,
        *,
        min_severity: Severity = Severity.INFO,
        timeout: float = 5.0,
    ) -> None:
        self.webhook_url = webhook_url
        self.min_severity = Severity(min_severity)
        self.timeout = timeout

    def _format(self, alert: Alert) -> dict:
        detail_txt = json.dumps(alert.detail, default=_json_default, sort_keys=True)
        text = (
            f"[{alert.severity.value.upper()}] {alert.event} "
            f"@ {alert.ts.isoformat()} :: {detail_txt}"
        )
        return {"text": text, "event": alert.event, "severity": alert.severity.value}

    def notify(
        self,
        alert: Union[Alert, Severity, str],
        event: str | None = None,
        detail: dict | None = None,
    ) -> None:
        alert = _coerce_alert(alert, event, detail)
        if _rank(alert.severity) < _rank(self.min_severity):
            return
        body = json.dumps(self._format(alert), default=_json_default).encode("utf-8")
        req = urlrequest.Request(
            self.webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urlrequest.urlopen(req, timeout=self.timeout)
        except URLError as exc:
            _log.warning("SlackAlerter POST failed (URLError): %s", exc)
        except Exception as exc:  # noqa: BLE001 — pipeline must not stop
            _log.warning("SlackAlerter POST failed: %s", exc)


class PagerDutyAlerter:
    """POST to PagerDuty Events API v2."""

    ENDPOINT = "https://events.pagerduty.com/v2/enqueue"

    def __init__(
        self,
        routing_key: str,
        *,
        min_severity: Severity = Severity.WARNING,
        timeout: float = 5.0,
    ) -> None:
        self.routing_key = routing_key
        self.min_severity = Severity(min_severity)
        self.timeout = timeout

    def _pd_severity(self, sev: Severity) -> str:
        # PagerDuty accepts: critical, error, warning, info
        return {
            Severity.INFO: "info",
            Severity.WARNING: "warning",
            Severity.CRITICAL: "critical",
        }[sev]

    def _build_payload(self, alert: Alert) -> dict:
        dedup_key = f"{alert.event}:{alert.detail.get('dedup_key', alert.event)}"
        return {
            "routing_key": self.routing_key,
            "event_action": "trigger",
            "dedup_key": dedup_key,
            "payload": {
                "summary": f"{alert.event} [{alert.severity.value}]",
                "source": "trading-algo",
                "severity": self._pd_severity(alert.severity),
                "custom_details": alert.detail,
                "timestamp": alert.ts.isoformat(),
            },
        }

    def notify(
        self,
        alert: Union[Alert, Severity, str],
        event: str | None = None,
        detail: dict | None = None,
    ) -> None:
        alert = _coerce_alert(alert, event, detail)
        if _rank(alert.severity) < _rank(self.min_severity):
            return
        payload = self._build_payload(alert)
        body = json.dumps(payload, default=_json_default).encode("utf-8")
        req = urlrequest.Request(
            self.ENDPOINT,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urlrequest.urlopen(req, timeout=self.timeout)
        except URLError as exc:
            _log.warning("PagerDutyAlerter POST failed (URLError): %s", exc)
        except Exception as exc:  # noqa: BLE001 — pipeline must not stop
            _log.warning("PagerDutyAlerter POST failed: %s", exc)


class FanoutAlerter:
    """Dispatch every alert to every child. One child's failure never blocks others."""

    def __init__(self, children: list[Alerter]) -> None:
        self.children = list(children)

    def notify(
        self,
        alert: Union[Alert, Severity, str],
        event: str | None = None,
        detail: dict | None = None,
    ) -> None:
        alert_obj = _coerce_alert(alert, event, detail)
        for child in self.children:
            try:
                child.notify(alert_obj)
            except Exception as exc:  # noqa: BLE001 — isolate child failures
                _log.warning(
                    "FanoutAlerter child %r raised, continuing: %s",
                    type(child).__name__,
                    exc,
                )
