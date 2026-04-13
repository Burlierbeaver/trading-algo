from __future__ import annotations

from typing import Literal

from monitor.db import Database


class KillAuditRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(self, action: Literal["halt", "resume"], note: str | None = None) -> int:
        value = await self._db.fetchval(
            """
            INSERT INTO kill_audit (action, note)
            VALUES ($1, $2)
            RETURNING id
            """,
            action,
            note,
        )
        return int(value)
