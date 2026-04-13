from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import fakeredis.aioredis
import pytest

from monitor.models import Alert


class FakeAlertsRepo:
    def __init__(self) -> None:
        self._rows: list[Alert] = []
        self._next_id = 1

    async def insert(self, alert: Alert) -> Alert:
        stored = alert.model_copy(
            update={
                "id": self._next_id,
                "created_at": datetime.now(tz=timezone.utc),
            }
        )
        self._next_id += 1
        self._rows.append(stored)
        return stored

    async def recent(self, limit: int = 50) -> list[Alert]:
        return list(reversed(self._rows))[:limit]

    async def acknowledge(self, alert_id: int) -> Alert | None:
        for i, row in enumerate(self._rows):
            if row.id == alert_id:
                acked = row.model_copy(update={"acknowledged_at": datetime.now(tz=timezone.utc)})
                self._rows[i] = acked
                return acked
        return None


class FakeKillAuditRepo:
    def __init__(self) -> None:
        self.records: list[tuple[str, str | None]] = []

    async def record(self, action: str, note: str | None = None) -> int:
        self.records.append((action, note))
        return len(self.records)


class FakePositionsRepo:
    def __init__(self, rows: list | None = None) -> None:
        self._rows = rows or []

    async def list_open(self, limit: int = 200) -> list:
        return list(self._rows[:limit])


class FakeTradesRepo:
    def __init__(self, rows: list | None = None) -> None:
        self._rows = rows or []

    async def recent(self, limit: int = 20) -> list:
        return list(self._rows[:limit])


@pytest.fixture
def redis():
    """Fresh fakeredis async client per test."""
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def alerts_repo() -> FakeAlertsRepo:
    return FakeAlertsRepo()


@pytest.fixture
def kill_audit_repo() -> FakeKillAuditRepo:
    return FakeKillAuditRepo()


@pytest.fixture
def positions_repo() -> FakePositionsRepo:
    return FakePositionsRepo()


@pytest.fixture
def trades_repo() -> FakeTradesRepo:
    return FakeTradesRepo()
