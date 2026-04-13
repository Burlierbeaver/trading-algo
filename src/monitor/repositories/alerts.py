from __future__ import annotations

from monitor.db import Database
from monitor.models import Alert


class AlertsRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(self, alert: Alert) -> Alert:
        row = await self._db.fetchrow(
            """
            INSERT INTO alerts (severity, source, title, detail)
            VALUES ($1, $2, $3, $4)
            RETURNING id, created_at, severity, source, title, detail, acknowledged_at
            """,
            alert.severity,
            alert.source,
            alert.title,
            alert.detail,
        )
        assert row is not None
        return Alert(**dict(row))

    async def recent(self, limit: int = 50) -> list[Alert]:
        rows = await self._db.fetch(
            """
            SELECT id, created_at, severity, source, title, detail, acknowledged_at
              FROM alerts
             ORDER BY created_at DESC
             LIMIT $1
            """,
            limit,
        )
        return [Alert(**dict(r)) for r in rows]

    async def acknowledge(self, alert_id: int) -> Alert | None:
        row = await self._db.fetchrow(
            """
            UPDATE alerts
               SET acknowledged_at = NOW()
             WHERE id = $1
         RETURNING id, created_at, severity, source, title, detail, acknowledged_at
            """,
            alert_id,
        )
        return Alert(**dict(row)) if row else None
