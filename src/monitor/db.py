from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import asyncpg

log = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class Database:
    """Thin wrapper around an asyncpg connection pool.

    Kept as a class (rather than a module global) so tests can construct and
    inject fakes cleanly.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self._pool is not None:
            return
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=1,
            max_size=8,
            command_timeout=10,
        )
        log.info("postgres pool connected")

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("database is not connected")
        return self._pool

    async def apply_schema(self) -> None:
        sql = SCHEMA_PATH.read_text()
        async with self.pool.acquire() as conn:
            await conn.execute(sql)

    async def fetch(self, query: str, *args: Any) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args: Any) -> asyncpg.Record | None:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args: Any) -> Any:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    async def execute(self, query: str, *args: Any) -> str:
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args)
