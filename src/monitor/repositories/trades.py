from __future__ import annotations

from monitor.db import Database
from monitor.models import Trade


class TradesRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def recent(self, limit: int = 20) -> list[Trade]:
        rows = await self._db.fetch(
            """
            SELECT id, symbol, side, quantity, price, pnl,
                   broker_order_id, strategy, executed_at
              FROM trades
             ORDER BY executed_at DESC, id DESC
             LIMIT $1
            """,
            limit,
        )
        return [Trade(**dict(r)) for r in rows]
