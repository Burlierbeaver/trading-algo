from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from trading_algo.killswitch import (
    KILLSWITCH_SCHEMA,
    InMemoryKillSwitch,
    KillSwitchState,
    PostgresKillSwitch,
)


# ---------------------------------------------------------------------------
# InMemoryKillSwitch-only tests
# ---------------------------------------------------------------------------


def test_inmemory_starts_enabled_by_default() -> None:
    ks = InMemoryKillSwitch()
    assert ks.is_enabled() is True
    st = ks.state()
    assert st.enabled is True
    assert st.reason is None
    assert st.actor is None
    assert isinstance(st.updated_at, datetime)


def test_inmemory_trip_disables_with_reason_actor_timestamp() -> None:
    ks = InMemoryKillSwitch()
    before = datetime.now(timezone.utc)
    st = ks.trip(reason="risk breach", actor="risk-engine")
    after = datetime.now(timezone.utc)

    assert ks.is_enabled() is False
    assert st.enabled is False
    assert st.reason == "risk breach"
    assert st.actor == "risk-engine"
    assert before <= st.updated_at <= after


def test_inmemory_trip_defaults_actor_to_system() -> None:
    ks = InMemoryKillSwitch()
    st = ks.trip(reason="boom")
    assert st.actor == "system"


def test_inmemory_enable_rearms_and_clears_reason() -> None:
    ks = InMemoryKillSwitch()
    ks.trip(reason="risk breach", actor="risk-engine")
    st = ks.enable(actor="operator-alice")

    assert ks.is_enabled() is True
    assert st.enabled is True
    assert st.reason is None
    assert st.actor == "operator-alice"


def test_inmemory_initialized_disabled() -> None:
    ks = InMemoryKillSwitch(enabled=False)
    assert ks.is_enabled() is False
    assert ks.state().enabled is False


def test_inmemory_state_returns_copy_not_shared_reference() -> None:
    ks = InMemoryKillSwitch()
    snap = ks.state()
    ks.trip(reason="x", actor="y")
    # snapshot taken before trip() must not reflect the later mutation
    assert snap.enabled is True
    assert snap.reason is None


# ---------------------------------------------------------------------------
# Parametrized behavioral tests across BOTH implementations
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Minimal psycopg cursor test double supporting the calls we use."""

    def __init__(self, store: dict[str, tuple]) -> None:
        self._store = store
        self._last_row: tuple | None = None

    # context-manager protocol
    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def execute(self, sql: str, params: tuple = ()) -> None:
        sql_norm = " ".join(sql.split()).upper()
        if sql_norm.startswith("SELECT ENABLED FROM SYSTEM_FLAGS"):
            key = params[0]
            row = self._store.get(key)
            self._last_row = (row[0],) if row is not None else None
        elif sql_norm.startswith("SELECT ENABLED, REASON, ACTOR, UPDATED_AT"):
            key = params[0]
            self._last_row = self._store.get(key)
        elif sql_norm.startswith("INSERT INTO SYSTEM_FLAGS"):
            # params layout:
            #   enable(): (key, actor, updated_at)      -> enabled=TRUE, reason=NULL
            #   trip():   (key, reason, actor, updated_at) -> enabled=FALSE
            if len(params) == 3:
                key, actor, updated_at = params
                self._store[key] = (True, None, actor, updated_at)
            elif len(params) == 4:
                key, reason, actor, updated_at = params
                self._store[key] = (False, reason, actor, updated_at)
            else:
                raise AssertionError(f"unexpected INSERT params: {params!r}")
            self._last_row = None
        elif sql_norm.startswith("CREATE TABLE IF NOT EXISTS SYSTEM_FLAGS"):
            self._last_row = None
        else:
            raise AssertionError(f"unexpected SQL: {sql!r}")

    def fetchone(self) -> tuple | None:
        return self._last_row


class _FakeConn:
    def __init__(self, store: dict[str, tuple]) -> None:
        self._store = store

    def __enter__(self) -> "_FakeConn":
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._store)


def _make_postgres_with_fake(store: dict[str, tuple]):
    """Return a (killswitch, patcher) pair; caller must stop() the patcher."""
    patcher = patch("psycopg.connect", side_effect=lambda dsn: _FakeConn(store))
    patcher.start()
    ks = PostgresKillSwitch("postgresql://fake")
    return ks, patcher


@pytest.fixture(params=["inmemory", "postgres"])
def killswitch(request):
    """Gives both implementations the same behavioral contract."""
    if request.param == "inmemory":
        yield InMemoryKillSwitch()
        return

    store: dict[str, tuple] = {
        # Seed the row so is_enabled() reads True initially.
        "trading_enabled": (True, None, None, datetime.now(timezone.utc)),
    }
    ks, patcher = _make_postgres_with_fake(store)
    try:
        yield ks
    finally:
        patcher.stop()


def test_starts_enabled(killswitch) -> None:
    assert killswitch.is_enabled() is True


def test_trip_then_enable_roundtrip(killswitch) -> None:
    trip_st = killswitch.trip(reason="drawdown limit", actor="risk-engine")
    assert isinstance(trip_st, KillSwitchState)
    assert trip_st.enabled is False
    assert trip_st.reason == "drawdown limit"
    assert trip_st.actor == "risk-engine"
    assert killswitch.is_enabled() is False

    en_st = killswitch.enable(actor="operator-bob")
    assert en_st.enabled is True
    assert en_st.reason is None
    assert en_st.actor == "operator-bob"
    assert killswitch.is_enabled() is True


def test_state_reflects_mutation(killswitch) -> None:
    killswitch.trip(reason="eod", actor="cron")
    st = killswitch.state()
    assert st.enabled is False
    assert st.reason == "eod"
    assert st.actor == "cron"


# ---------------------------------------------------------------------------
# PostgresKillSwitch fail-closed tests
# ---------------------------------------------------------------------------


def test_postgres_is_enabled_fail_closed_on_connect_exception() -> None:
    ks = PostgresKillSwitch("postgresql://unreachable")
    with patch(
        "psycopg.connect", side_effect=RuntimeError("connection refused")
    ):
        # MUST NOT raise; MUST return False.
        assert ks.is_enabled() is False


def test_postgres_is_enabled_fail_closed_on_timeout() -> None:
    ks = PostgresKillSwitch("postgresql://slow")
    with patch("psycopg.connect", side_effect=TimeoutError("timeout")):
        assert ks.is_enabled() is False


def test_postgres_is_enabled_fail_closed_on_missing_row() -> None:
    store: dict[str, tuple] = {}  # no row
    with patch("psycopg.connect", side_effect=lambda dsn: _FakeConn(store)):
        ks = PostgresKillSwitch("postgresql://fake")
        assert ks.is_enabled() is False


def test_postgres_is_enabled_logs_warning_on_failure(caplog) -> None:
    ks = PostgresKillSwitch("postgresql://unreachable")
    with patch("psycopg.connect", side_effect=RuntimeError("boom")):
        with caplog.at_level("WARNING", logger="trading_algo.killswitch"):
            assert ks.is_enabled() is False
    assert any("fail-closed" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_schema_contains_system_flags_and_is_parseable() -> None:
    assert "system_flags" in KILLSWITCH_SCHEMA
    assert "CREATE TABLE" in KILLSWITCH_SCHEMA.upper()
    # Sanity: the required columns appear.
    for col in ("key", "enabled", "reason", "actor", "updated_at"):
        assert col in KILLSWITCH_SCHEMA

    # Tokenization check — a naive proxy for "valid SQL": statement
    # is a single CREATE TABLE terminated by a semicolon with balanced parens.
    stripped = KILLSWITCH_SCHEMA.strip().rstrip(";")
    assert stripped.count("(") == stripped.count(")")


def test_postgres_init_schema_executes_create_table() -> None:
    store: dict[str, tuple] = {}
    executed: list[str] = []

    class _SpyCursor(_FakeCursor):
        def execute(self, sql: str, params: tuple = ()) -> None:
            executed.append(sql)
            super().execute(sql, params)

    class _SpyConn(_FakeConn):
        def cursor(self) -> _SpyCursor:
            return _SpyCursor(self._store)

    with patch("psycopg.connect", side_effect=lambda dsn: _SpyConn(store)):
        ks = PostgresKillSwitch("postgresql://fake")
        ks.init_schema()

    assert any("CREATE TABLE" in sql.upper() for sql in executed)
    assert any("system_flags" in sql for sql in executed)


# ---------------------------------------------------------------------------
# Protocol conformance (structural)
# ---------------------------------------------------------------------------


def test_implementations_have_required_methods() -> None:
    for cls in (InMemoryKillSwitch, PostgresKillSwitch):
        for name in ("is_enabled", "state", "enable", "trip"):
            assert callable(getattr(cls, name)), f"{cls.__name__}.{name}"
