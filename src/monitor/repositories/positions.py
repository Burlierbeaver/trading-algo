from __future__ import annotations

from monitor.db import Database
from monitor.models import Position


class PositionsRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_open(self, limit: int = 200) -> list[Position]:
        rows = await self._db.fetch(
            """
            SELECT symbol, quantity, avg_price, market_value,
                   unrealized_pnl, realized_pnl, updated_at
              FROM positions
             WHERE quantity <> 0
             ORDER BY ABS(quantity) DESC, symbol ASC
             LIMIT $1
            """,
            limit,
        )
        return [Position(**dict(r)) for r in rows]
