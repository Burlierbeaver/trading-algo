from __future__ import annotations

import json
import logging
from typing import Protocol

import redis.asyncio as aioredis

from monitor.redis_client import CHANNEL_ALERTS, KEY_ENGINE_HALTED
from monitor.repositories.kill_audit import KillAuditRepo

log = logging.getLogger(__name__)


class _AlertPublisher(Protocol):
    async def publish(self, channel: str, message: str) -> int: ...


class KillSwitch:
    """Controls the `engine:halted` Redis flag.

    Halt is intentionally minimal: flip the flag to "1", write an audit row,
    publish an info alert. Resume is the inverse. Operators unwind existing
    positions themselves (per design decision D2).
    """

    def __init__(self, redis: aioredis.Redis, audit: KillAuditRepo) -> None:
        self._redis = redis
        self._audit = audit

    async def is_halted(self) -> bool:
        value = await self._redis.get(KEY_ENGINE_HALTED)
        return value == "1"

    async def halt(self, note: str | None = None) -> None:
        await self._redis.set(KEY_ENGINE_HALTED, "1")
        await self._audit.record("halt", note)
        await self._publish_alert(
            severity="warning",
            title="Engine halted",
            detail=note or "Halt triggered from dashboard.",
        )
        log.warning("engine halted (note=%s)", note)

    async def resume(self, note: str | None = None) -> None:
        await self._redis.set(KEY_ENGINE_HALTED, "0")
        await self._audit.record("resume", note)
        await self._publish_alert(
            severity="info",
            title="Engine resumed",
            detail=note or "Resume triggered from dashboard.",
        )
        log.info("engine resumed (note=%s)", note)

    async def _publish_alert(self, *, severity: str, title: str, detail: str) -> None:
        payload = json.dumps(
            {
                "severity": severity,
                "source": "dashboard.kill",
                "title": title,
                "detail": detail,
            }
        )
        try:
            await self._redis.publish(CHANNEL_ALERTS, payload)
        except Exception:
            log.exception("failed to publish kill-switch alert")
