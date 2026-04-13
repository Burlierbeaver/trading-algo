from __future__ import annotations

import pytest

from monitor.models import Alert, AlertEvent
from monitor.services.alert_dispatcher import AlertDispatcher


class RecordingNotifier:
    def __init__(self, name: str = "rec", fail: bool = False) -> None:
        self.name = name
        self._fail = fail
        self.received: list[Alert] = []

    async def send(self, alert: Alert) -> None:
        if self._fail:
            raise RuntimeError("notifier exploded")
        self.received.append(alert)


@pytest.mark.asyncio
async def test_dispatch_persists_and_notifies(redis, alerts_repo):
    notif = RecordingNotifier()
    dispatcher = AlertDispatcher(redis=redis, alerts_repo=alerts_repo, notifiers=[notif])

    event = AlertEvent(severity="warning", source="test", title="Something", detail="details")
    alert = await dispatcher.dispatch(event)

    assert alert.id is not None
    assert alert.severity == "warning"
    assert alert.title == "Something"
    assert notif.received == [alert]
    persisted = await alerts_repo.recent(limit=10)
    assert any(a.id == alert.id for a in persisted)


@pytest.mark.asyncio
async def test_dispatch_does_not_raise_when_notifier_fails(redis, alerts_repo):
    ok = RecordingNotifier("ok")
    broken = RecordingNotifier("broken", fail=True)
    dispatcher = AlertDispatcher(redis=redis, alerts_repo=alerts_repo, notifiers=[broken, ok])

    event = AlertEvent(severity="info", source="test", title="Keep going")
    alert = await dispatcher.dispatch(event)

    # Persisted despite broken notifier
    assert alert.id is not None
    # Non-broken notifier still received
    assert ok.received == [alert]


@pytest.mark.asyncio
async def test_local_subscriber_receives_dispatched_alert(redis, alerts_repo):
    dispatcher = AlertDispatcher(redis=redis, alerts_repo=alerts_repo, notifiers=[])
    queue = dispatcher.subscribe_local()

    event = AlertEvent(severity="critical", source="x", title="boom")
    await dispatcher.dispatch(event)

    received = await queue.get()
    assert received.title == "boom"
    dispatcher.unsubscribe_local(queue)
