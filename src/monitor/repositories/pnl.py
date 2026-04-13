from __future__ import annotations

from monitor.db import Database
from monitor.models import PnLSnapshot


class PnLRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def recent(self, limit: int = 50) -> list[PnLSnapshot]:
        rows = await self._db.fetch(
            """
            SELECT id, snapshot_at, equity, cash,
                   realized_pnl, unrealized_pnl, daily_pnl
              FROM pnl_snapshots
             ORDER BY snapshot_at DESC
             LIMIT $1
            """,
            limit,
        )
        return [PnLSnapshot(**dict(r)) for r in rows]

    async def latest(self) -> PnLSnapshot | None:
        row = await self._db.fetchrow(
            """
            SELECT id, snapshot_at, equity, cash,
                   realized_pnl, unrealized_pnl, daily_pnl
              FROM pnl_snapshots
             ORDER BY snapshot_at DESC
             LIMIT 1
            """
        )
        return PnLSnapshot(**dict(row)) if row else None
