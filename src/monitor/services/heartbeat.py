from __future__ import annotations

import asyncio
import json
import logging
import time

import redis.asyncio as aioredis

from monitor.redis_client import CHANNEL_ALERTS, KEY_ENGINE_HEARTBEAT

log = logging.getLogger(__name__)


class HeartbeatMonitor:
    """Polls `engine:heartbeat` and publishes infra alerts when stale.

    The engine writes a numeric (epoch seconds) string every few seconds. We
    read it, compare to wall clock, and publish a critical alert if the value
    is older than `stale_after`. To avoid spam, repeat alerts are suppressed
    for `repeat_suppress` seconds.
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        *,
        poll_interval: float,
        stale_after: float,
        repeat_suppress: float,
    ) -> None:
        self._redis = redis
        self._poll_interval = poll_interval
        self._stale_after = stale_after
        self._repeat_suppress = repeat_suppress
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._last_stale_alert_ts: float = 0.0
        self._last_recovery_alert_ts: float = 0.0
        self._was_stale: bool = False

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="heartbeat-monitor")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=self._poll_interval + 1)
            except asyncio.TimeoutError:
                self._task.cancel()
            self._task = None

    async def check_once(self, now: float | None = None) -> bool:
        """Single iteration of the loop. Returns True if a stale-alert fired.

        Split out for tests — no sleep, no asyncio.create_task.
        """
        now = now if now is not None else time.time()
        raw = await self._redis.get(KEY_ENGINE_HEARTBEAT)
        age: float | None = None
        if raw is not None:
            try:
                age = now - float(raw)
            except ValueError:
                log.warning("heartbeat value is not numeric: %r", raw)

        is_stale = age is None or age > self._stale_after

        if is_stale:
            if now - self._last_stale_alert_ts >= self._repeat_suppress:
                await self._publish(
                    severity="critical",
                    title="Engine heartbeat stale",
                    detail=(
                        "No heartbeat from strategy engine"
                        if age is None
                        else f"Heartbeat is {age:.1f}s old (threshold {self._stale_after:.0f}s)"
                    ),
                )
                self._last_stale_alert_ts = now
                self._was_stale = True
                return True
            self._was_stale = True
            return False

        if self._was_stale:
            await self._publish(
                severity="info",
                title="Engine heartbeat recovered",
                detail=f"Heartbeat age {age:.1f}s",
            )
            self._last_recovery_alert_ts = now
            self._was_stale = False
        return False

    async def _run(self) -> None:
        log.info(
            "heartbeat monitor running (poll=%.1fs, stale_after=%.0fs)",
            self._poll_interval,
            self._stale_after,
        )
        while not self._stop.is_set():
            try:
                await self.check_once()
            except Exception:
                log.exception("heartbeat monitor error")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_interval)
            except asyncio.TimeoutError:
                pass

    async def _publish(self, *, severity: str, title: str, detail: str) -> None:
        payload = json.dumps(
            {
                "severity": severity,
                "source": "dashboard.heartbeat",
                "title": title,
                "detail": detail,
            }
        )
        try:
            await self._redis.publish(CHANNEL_ALERTS, payload)
        except Exception:
            log.exception("failed to publish heartbeat alert")
