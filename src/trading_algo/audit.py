from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator, Protocol
from uuid import UUID, uuid4


@dataclass(frozen=True)
class AuditRecord:
    id: UUID
    correlation_id: UUID
    stage: str
    event_id: str | None
    payload: dict[str, Any]
    created_at: datetime


class AuditLog(Protocol):
    def record(
        self, stage: str, *, event_id: str | None, payload: dict
    ) -> AuditRecord: ...

    def query(self, *, correlation_id: UUID) -> list[AuditRecord]: ...


_correlation: ContextVar[UUID | None] = ContextVar(
    "trading_algo_audit_correlation", default=None
)


def current_correlation_id() -> UUID | None:
    """Return the correlation id bound to the current context, or ``None``."""
    return _correlation.get()


def set_correlation_id(cid: UUID) -> None:
    """Bind ``cid`` as the current context's correlation id."""
    _correlation.set(cid)


@contextmanager
def correlation(cid: UUID | None = None) -> Iterator[UUID]:
    """Scoped correlation_id. Defaults to a fresh uuid4. Yields the cid.
    Restores previous value on exit. Use: ``with correlation() as cid: ...``"""
    if cid is None:
        cid = uuid4()
    token = _correlation.set(cid)
    try:
        yield cid
    finally:
        _correlation.reset(token)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_correlation() -> UUID:
    existing = _correlation.get()
    if existing is not None:
        return existing
    return uuid4()


def _encode_payload(payload: dict[str, Any]) -> str:
    """JSON-encode payload so Decimal/datetime become strings."""
    return json.dumps(payload, default=str)


class InMemoryAuditLog:
    """Implements :class:`AuditLog`. Records are kept in a list for tests."""

    records: list[AuditRecord]

    def __init__(self) -> None:
        self.records = []

    def record(
        self, stage: str, *, event_id: str | None, payload: dict
    ) -> AuditRecord:
        cid = _resolve_correlation()
        # Round-trip payload through JSON with the same encoder used by the
        # Postgres backend so InMemory behaviour matches production semantics.
        encoded = json.loads(_encode_payload(payload))
        rec = AuditRecord(
            id=uuid4(),
            correlation_id=cid,
            stage=stage,
            event_id=event_id,
            payload=encoded,
            created_at=_utcnow(),
        )
        self.records.append(rec)
        return rec

    def query(self, *, correlation_id: UUID) -> list[AuditRecord]:
        matches = [r for r in self.records if r.correlation_id == correlation_id]
        return sorted(matches, key=lambda r: r.created_at)


AUDIT_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id              UUID PRIMARY KEY,
    correlation_id  UUID NOT NULL,
    stage           TEXT NOT NULL,
    event_id        TEXT,
    payload         JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS audit_log_correlation_idx ON audit_log (correlation_id);
CREATE INDEX IF NOT EXISTS audit_log_created_idx     ON audit_log (created_at);
"""


class PostgresAuditLog:
    """Implements :class:`AuditLog` backed by Postgres via psycopg v3.

    Follows the same pattern as :mod:`trading_algo.bridges.strategy_engine`:
    the module is imported lazily so the class can be referenced without
    psycopg installed, but instantiation requires it."""

    def __init__(self, dsn: str) -> None:
        try:
            import psycopg  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "PostgresAuditLog requires psycopg — install via the broker-adapter extras"
            ) from e
        self._dsn = dsn

    def init_schema(self) -> None:
        import psycopg

        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(AUDIT_LOG_SCHEMA)

    def record(
        self, stage: str, *, event_id: str | None, payload: dict
    ) -> AuditRecord:
        import psycopg

        rec_id = uuid4()
        cid = _resolve_correlation()
        created_at = _utcnow()
        encoded = _encode_payload(payload)
        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_log
                    (id, correlation_id, stage, event_id, payload, created_at)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                """,
                (rec_id, cid, stage, event_id, encoded, created_at),
            )
        # Return the record reflecting what was persisted (payload round-tripped
        # through JSON so it matches the JSONB column semantics).
        return AuditRecord(
            id=rec_id,
            correlation_id=cid,
            stage=stage,
            event_id=event_id,
            payload=json.loads(encoded),
            created_at=created_at,
        )

    def query(self, *, correlation_id: UUID) -> list[AuditRecord]:
        import psycopg

        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, correlation_id, stage, event_id, payload, created_at
                  FROM audit_log
                 WHERE correlation_id = %s
                 ORDER BY created_at ASC
                """,
                (correlation_id,),
            )
            rows = cur.fetchall()
        out: list[AuditRecord] = []
        for rid, cid, stage, event_id, payload, created_at in rows:
            out.append(
                AuditRecord(
                    id=rid,
                    correlation_id=cid,
                    stage=stage,
                    event_id=event_id,
                    payload=payload if isinstance(payload, dict) else json.loads(payload),
                    created_at=created_at,
                )
            )
        return out
