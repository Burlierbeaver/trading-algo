from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterable

import redis.asyncio as aioredis

from monitor.models import Alert, AlertEvent
from monitor.notifiers.base import Notifier
from monitor.redis_client import CHANNEL_ALERTS
from monitor.repositories.alerts import AlertsRepo

log = logging.getLogger(__name__)


class AlertDispatcher:
    """Subscribes to `alerts:events`, persists, and fans out to notifiers.

    Persistence happens first — if a notifier fails we log but still keep the
    alert record. Notifier failures never abort the subscriber loop.
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        alerts_repo: AlertsRepo,
        notifiers: Iterable[Notifier],
    ) -> None:
        self._redis = redis
        self._repo = alerts_repo
        self._notifiers: list[Notifier] = list(notifiers)
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._listeners: list[asyncio.Queue[Alert]] = []

    def subscribe_local(self) -> asyncio.Queue[Alert]:
        """Register a process-local listener (used by SSE stream).

        Each subscriber gets its own bounded queue; dispatcher drops messages
        for slow consumers rather than blocking.
        """

        queue: asyncio.Queue[Alert] = asyncio.Queue(maxsize=64)
        self._listeners.append(queue)
        return queue

    def unsubscribe_local(self, queue: asyncio.Queue[Alert]) -> None:
        try:
            self._listeners.remove(queue)
        except ValueError:
            pass

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="alert-dispatcher")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def dispatch(self, event: AlertEvent) -> Alert:
        """Persist + notify for a single event. Public entry point for tests."""
        alert = await self._repo.insert(
            Alert(
                severity=event.severity,
                source=event.source,
                title=event.title,
                detail=event.detail,
            )
        )
        for notifier in self._notifiers:
            try:
                await notifier.send(alert)
            except Exception:
                log.exception("notifier %s failed for alert %s", notifier.name, alert.id)
        self._broadcast_local(alert)
        return alert

    def _broadcast_local(self, alert: Alert) -> None:
        for queue in list(self._listeners):
            try:
                queue.put_nowait(alert)
            except asyncio.QueueFull:
                log.warning("dropping alert for slow local listener")

    async def _run(self) -> None:
        log.info("alert dispatcher subscribing to %s", CHANNEL_ALERTS)
        pubsub = self._redis.pubsub()
        try:
            await pubsub.subscribe(CHANNEL_ALERTS)
            while not self._stop.is_set():
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg is None:
                    continue
                data = msg.get("data")
                if not data:
                    continue
                try:
                    event = AlertEvent(**json.loads(data))
                except Exception:
                    log.exception("bad alert event payload: %r", data)
                    continue
                try:
                    await self.dispatch(event)
                except Exception:
                    log.exception("dispatch failed")
        finally:
            try:
                await pubsub.unsubscribe(CHANNEL_ALERTS)
                await pubsub.aclose()
            except Exception:
                pass
