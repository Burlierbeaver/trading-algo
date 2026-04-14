from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

logger = logging.getLogger(__name__)


KILLSWITCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS system_flags (
    key         TEXT PRIMARY KEY,
    enabled     BOOLEAN NOT NULL,
    reason      TEXT,
    actor       TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class KillSwitchState:
    enabled: bool
    reason: str | None
    actor: str | None
    updated_at: datetime


class KillSwitch(Protocol):
    """Halts new order submission. Tripped by a human or the risk engine,
    re-armed only by a human. This is NOT market-hours logic."""

    def is_enabled(self) -> bool: ...  # fail-closed: returns False on error
    def state(self) -> KillSwitchState: ...
    def enable(self, *, actor: str) -> KillSwitchState: ...  # human re-arm
    def trip(
        self, *, reason: str, actor: str = "system"
    ) -> KillSwitchState: ...  # halt


class InMemoryKillSwitch:
    """In-process KillSwitch for tests and single-process deployments."""

    def __init__(self, *, enabled: bool = True) -> None:
        self._state = KillSwitchState(
            enabled=enabled,
            reason=None,
            actor=None,
            updated_at=_utcnow(),
        )

    def is_enabled(self) -> bool:
        return self._state.enabled

    def state(self) -> KillSwitchState:
        return KillSwitchState(
            enabled=self._state.enabled,
            reason=self._state.reason,
            actor=self._state.actor,
            updated_at=self._state.updated_at,
        )

    def enable(self, *, actor: str) -> KillSwitchState:
        self._state = KillSwitchState(
            enabled=True,
            reason=None,
            actor=actor,
            updated_at=_utcnow(),
        )
        return self.state()

    def trip(self, *, reason: str, actor: str = "system") -> KillSwitchState:
        self._state = KillSwitchState(
            enabled=False,
            reason=reason,
            actor=actor,
            updated_at=_utcnow(),
        )
        return self.state()


class PostgresKillSwitch:
    """Postgres-backed KillSwitch using the ``system_flags`` table.

    ``is_enabled()`` is fail-closed: ANY exception (connection failure,
    timeout, missing row) returns False and logs a warning. This is the
    safety guarantee — if we can't verify trading is enabled, we refuse
    to trade."""

    def __init__(self, dsn: str, *, key: str = "trading_enabled") -> None:
        try:
            import psycopg  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "PostgresKillSwitch requires psycopg — install via the broker-adapter extras"
            ) from e
        self._dsn = dsn
        self._key = key

    def init_schema(self) -> None:
        import psycopg

        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(KILLSWITCH_SCHEMA)

    def is_enabled(self) -> bool:
        import psycopg

        try:
            with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT enabled FROM system_flags WHERE key = %s",
                    (self._key,),
                )
                row = cur.fetchone()
            if row is None:
                logger.warning(
                    "killswitch: no row for key=%s — fail-closed (disabled)",
                    self._key,
                )
                return False
            return bool(row[0])
        except Exception as e:  # noqa: BLE001 — fail-closed is the point
            logger.warning(
                "killswitch: is_enabled() failed (%s) — fail-closed (disabled)",
                e,
            )
            return False

    def state(self) -> KillSwitchState:
        import psycopg

        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT enabled, reason, actor, updated_at
                  FROM system_flags
                 WHERE key = %s
                """,
                (self._key,),
            )
            row = cur.fetchone()
        if row is None:
            # No row yet — mirror fail-closed semantics for state readers.
            return KillSwitchState(
                enabled=False,
                reason="uninitialized",
                actor=None,
                updated_at=_utcnow(),
            )
        enabled, reason, actor, updated_at = row
        return KillSwitchState(
            enabled=bool(enabled),
            reason=reason,
            actor=actor,
            updated_at=updated_at,
        )

    def enable(self, *, actor: str) -> KillSwitchState:
        import psycopg

        now = _utcnow()
        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO system_flags (key, enabled, reason, actor, updated_at)
                VALUES (%s, TRUE, NULL, %s, %s)
                ON CONFLICT (key) DO UPDATE
                   SET enabled = TRUE,
                       reason  = NULL,
                       actor   = EXCLUDED.actor,
                       updated_at = EXCLUDED.updated_at
                """,
                (self._key, actor, now),
            )
        return KillSwitchState(
            enabled=True, reason=None, actor=actor, updated_at=now
        )

    def trip(self, *, reason: str, actor: str = "system") -> KillSwitchState:
        import psycopg

        now = _utcnow()
        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO system_flags (key, enabled, reason, actor, updated_at)
                VALUES (%s, FALSE, %s, %s, %s)
                ON CONFLICT (key) DO UPDATE
                   SET enabled = FALSE,
                       reason  = EXCLUDED.reason,
                       actor   = EXCLUDED.actor,
                       updated_at = EXCLUDED.updated_at
                """,
                (self._key, reason, actor, now),
            )
        return KillSwitchState(
            enabled=False, reason=reason, actor=actor, updated_at=now
        )
