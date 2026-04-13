from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Callable, Protocol

from nlp_signal import Signal
from risk_manager import TradeIntent
from risk_manager.types import OrderType, Side


class IntentStore(Protocol):
    """Transport abstraction for the TypeScript strategy-engine bridge.

    The TS strategy engine (worktree
    ``strategy-engine-trade-signal-processing``) runs as a separate service.
    Per the project architecture, cross-component communication goes through
    shared Postgres tables.

      - ``publish_signal`` → INSERT into ``strategy_signals``
      - ``pop_intent``     → SELECT + DELETE FROM ``strategy_intents``
                             WHERE source_event_id = ?"""

    def publish_signal(self, signal: Signal) -> None: ...
    def pop_intent(self, source_event_id: str) -> TradeIntent | None: ...


class StrategyEngineBridge:
    """``Strategy`` protocol implementation that round-trips signals through
    an external strategy engine via a shared ``IntentStore`` transport."""

    def __init__(self, store: IntentStore) -> None:
        self._store = store

    def on_signal(self, signal: Signal) -> TradeIntent | None:
        self._store.publish_signal(signal)
        return self._store.pop_intent(signal.source_event_id)


class InMemoryIntentStore:
    """Test double that routes through a synchronous callback."""

    def __init__(self, compute: Callable[[Signal], TradeIntent | None]) -> None:
        self._compute = compute
        self.published: list[Signal] = []

    def publish_signal(self, signal: Signal) -> None:
        self.published.append(signal)

    def pop_intent(self, source_event_id: str) -> TradeIntent | None:
        for s in self.published:
            if s.source_event_id == source_event_id:
                return self._compute(s)
        return None


STRATEGY_ENGINE_SCHEMA = """
CREATE TABLE IF NOT EXISTS strategy_signals (
    id             BIGSERIAL PRIMARY KEY,
    source_event_id TEXT NOT NULL,
    ticker          TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    score           NUMERIC NOT NULL,
    magnitude       NUMERIC NOT NULL,
    confidence      NUMERIC NOT NULL,
    rationale       TEXT NOT NULL,
    extracted_at    TIMESTAMPTZ NOT NULL,
    published_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    consumed        BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_strategy_signals_unconsumed
    ON strategy_signals (published_at) WHERE NOT consumed;

CREATE TABLE IF NOT EXISTS strategy_intents (
    id               BIGSERIAL PRIMARY KEY,
    source_event_id  TEXT NOT NULL,
    symbol           TEXT NOT NULL,
    side             TEXT NOT NULL,
    order_type       TEXT NOT NULL,
    client_order_id  TEXT NOT NULL UNIQUE,
    strategy_id      TEXT NOT NULL,
    qty              NUMERIC,
    notional         NUMERIC,
    limit_price      NUMERIC,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_strategy_intents_event
    ON strategy_intents (source_event_id);
"""


class PostgresIntentStore:
    """Postgres-backed IntentStore. Uses a connection string (libpq DSN).

    The TS strategy engine consumes rows from ``strategy_signals`` and writes
    to ``strategy_intents`` — this class publishes to the former and pops
    from the latter with ``DELETE … RETURNING`` for at-most-once delivery."""

    def __init__(self, dsn: str) -> None:
        try:
            import psycopg  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "PostgresIntentStore requires psycopg — install via the broker-adapter extras"
            ) from e
        self._dsn = dsn

    def init_schema(self) -> None:
        import psycopg
        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(STRATEGY_ENGINE_SCHEMA)

    def publish_signal(self, signal: Signal) -> None:
        import psycopg
        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO strategy_signals
                  (source_event_id, ticker, event_type, score, magnitude,
                   confidence, rationale, extracted_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    signal.source_event_id,
                    signal.ticker,
                    signal.event_type.value,
                    signal.score,
                    signal.magnitude,
                    signal.confidence,
                    signal.rationale,
                    signal.extracted_at,
                ),
            )

    def pop_intent(self, source_event_id: str) -> TradeIntent | None:
        import psycopg
        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM strategy_intents
                 WHERE id = (
                     SELECT id FROM strategy_intents
                      WHERE source_event_id = %s
                      ORDER BY created_at
                      FOR UPDATE SKIP LOCKED
                      LIMIT 1
                 )
                RETURNING symbol, side, order_type, client_order_id, strategy_id,
                          qty, notional, limit_price
                """,
                (source_event_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return _row_to_intent(row)


def _row_to_intent(row: tuple[Any, ...]) -> TradeIntent:
    symbol, side, order_type, cid, strategy_id, qty, notional, limit_price = row
    return TradeIntent(
        symbol=symbol,
        side=Side(side),
        order_type=OrderType(order_type),
        client_order_id=cid,
        strategy_id=strategy_id,
        qty=Decimal(qty) if qty is not None else None,
        notional=Decimal(notional) if notional is not None else None,
        limit_price=Decimal(limit_price) if limit_price is not None else None,
    )


def intent_to_insert_params(intent: TradeIntent, source_event_id: str) -> dict[str, Any]:
    """Helper for the TS engine's consumer — documents the row shape it must write."""
    return {
        "source_event_id": source_event_id,
        "symbol": intent.symbol,
        "side": intent.side.value,
        "order_type": intent.order_type.value,
        "client_order_id": intent.client_order_id,
        "strategy_id": intent.strategy_id,
        "qty": str(intent.qty) if intent.qty is not None else None,
        "notional": str(intent.notional) if intent.notional is not None else None,
        "limit_price": str(intent.limit_price) if intent.limit_price is not None else None,
    }


def serialize_signal(signal: Signal) -> str:
    """JSON wire format the TS engine reads off ``strategy_signals``."""
    return json.dumps(
        {
            "source_event_id": signal.source_event_id,
            "ticker": signal.ticker,
            "event_type": signal.event_type.value,
            "score": signal.score,
            "magnitude": signal.magnitude,
            "confidence": signal.confidence,
            "rationale": signal.rationale,
            "extracted_at": signal.extracted_at.isoformat(),
        }
    )
