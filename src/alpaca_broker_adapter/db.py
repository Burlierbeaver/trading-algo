from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from importlib import resources
from pathlib import Path
from typing import Any, Iterable, Optional, Protocol
from uuid import UUID

from .config import Settings
from .models import Fill, OrderRequest, OrderStatus, OrderType


# ---------------------------------------------------------------------------
# Repo protocol — the narrow surface used by the adapter
# ---------------------------------------------------------------------------


class OrderRepo(Protocol):
    def init_schema(self) -> None: ...
    def insert_pending_order(self, order: OrderRequest, mode: str) -> None: ...
    def mark_submitted(
        self,
        client_order_id: UUID,
        broker_order_id: str,
        status: OrderStatus,
        raw: dict[str, Any],
    ) -> None: ...
    def update_order_state(
        self,
        broker_order_id: str,
        status: OrderStatus,
        filled_qty: Decimal,
        filled_avg_price: Optional[Decimal],
        terminal_at: Optional[datetime],
        raw: dict[str, Any],
    ) -> None: ...
    def insert_fill(self, fill: Fill, raw: dict[str, Any]) -> None: ...
    def list_non_terminal_orders(self) -> list[dict[str, Any]]: ...
    def get_order_by_client_id(self, client_order_id: UUID) -> Optional[dict[str, Any]]: ...


# ---------------------------------------------------------------------------
# Postgres implementation (psycopg3)
# ---------------------------------------------------------------------------


def _schema_sql() -> str:
    return resources.files("alpaca_broker_adapter").joinpath("schema.sql").read_text()


class PostgresOrderRepo:
    def __init__(self, settings: Settings) -> None:
        import psycopg
        from psycopg_pool import ConnectionPool  # type: ignore

        self._psycopg = psycopg
        self._pool = ConnectionPool(conninfo=settings.database_url, min_size=1, max_size=5, open=True)

    def close(self) -> None:
        self._pool.close()

    # ------------------------------------------------------------------ ddl

    def init_schema(self) -> None:
        sql = _schema_sql()
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(sql)

    # ---------------------------------------------------------------- writes

    def insert_pending_order(self, order: OrderRequest, mode: str) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO orders (
                    client_order_id, symbol, side, qty, notional,
                    order_type, limit_price, time_in_force, status, mode
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (client_order_id) DO NOTHING
                """,
                (
                    str(order.client_order_id),
                    order.symbol,
                    order.side.value,
                    _dec(order.qty),
                    _dec(order.notional),
                    order.order_type.value,
                    _dec(order.limit_price),
                    order.time_in_force.value,
                    OrderStatus.PENDING.value,
                    mode,
                ),
            )

    def mark_submitted(
        self,
        client_order_id: UUID,
        broker_order_id: str,
        status: OrderStatus,
        raw: dict[str, Any],
    ) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE orders
                SET broker_order_id = %s,
                    status = %s,
                    raw = %s
                WHERE client_order_id = %s
                """,
                (broker_order_id, status.value, json.dumps(raw, default=_json_default), str(client_order_id)),
            )

    def update_order_state(
        self,
        broker_order_id: str,
        status: OrderStatus,
        filled_qty: Decimal,
        filled_avg_price: Optional[Decimal],
        terminal_at: Optional[datetime],
        raw: dict[str, Any],
    ) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE orders
                SET status = %s,
                    filled_qty = %s,
                    filled_avg_price = %s,
                    terminal_at = COALESCE(terminal_at, %s),
                    raw = %s
                WHERE broker_order_id = %s
                """,
                (
                    status.value,
                    _dec(filled_qty),
                    _dec(filled_avg_price),
                    terminal_at,
                    json.dumps(raw, default=_json_default),
                    broker_order_id,
                ),
            )

    def insert_fill(self, fill: Fill, raw: dict[str, Any]) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO fills (
                    broker_order_id, broker_fill_id, symbol, side,
                    qty, price, filled_at, raw
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (broker_fill_id) DO NOTHING
                """,
                (
                    fill.broker_order_id,
                    fill.broker_fill_id,
                    fill.symbol,
                    fill.side.value,
                    _dec(fill.qty),
                    _dec(fill.price),
                    fill.filled_at,
                    json.dumps(raw, default=_json_default),
                ),
            )

    # ----------------------------------------------------------------- reads

    def list_non_terminal_orders(self) -> list[dict[str, Any]]:
        terminal = [s.value for s in OrderStatus if s.is_terminal]
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT client_order_id, broker_order_id, symbol, side, status
                FROM orders
                WHERE broker_order_id IS NOT NULL
                  AND status NOT IN %s
                ORDER BY submitted_at
                """,
                (tuple(terminal),),
            )
            rows = cur.fetchall()
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, r)) for r in rows]

    def get_order_by_client_id(self, client_order_id: UUID) -> Optional[dict[str, Any]]:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM orders WHERE client_order_id = %s",
                (str(client_order_id),),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dec(v: Optional[Decimal]) -> Optional[str]:
    if v is None:
        return None
    return str(v)


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (Decimal, UUID)):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"not JSON serializable: {type(obj).__name__}")


__all__: Iterable[str] = [
    "OrderRepo",
    "PostgresOrderRepo",
]
