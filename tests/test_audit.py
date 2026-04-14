from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from trading_algo.audit import (
    AUDIT_LOG_SCHEMA,
    AuditRecord,
    InMemoryAuditLog,
    PostgresAuditLog,
    correlation,
    current_correlation_id,
    set_correlation_id,
)


def test_record_without_active_correlation_generates_fresh_uuid_each_call():
    log = InMemoryAuditLog()

    r1 = log.record("raw_event", event_id="e1", payload={"a": 1})
    r2 = log.record("raw_event", event_id="e2", payload={"a": 2})

    assert isinstance(r1.correlation_id, UUID)
    assert isinstance(r2.correlation_id, UUID)
    assert r1.correlation_id != r2.correlation_id
    # The contextvar itself remains unset.
    assert current_correlation_id() is None


def test_correlation_context_shares_cid_and_resets_on_exit():
    log = InMemoryAuditLog()

    with correlation() as cid:
        assert isinstance(cid, UUID)
        r1 = log.record("raw_event", event_id="e1", payload={})
        r2 = log.record("signal", event_id="e1", payload={})
        assert r1.correlation_id == cid
        assert r2.correlation_id == cid

    # After the block, a new record gets a fresh cid.
    r3 = log.record("raw_event", event_id="e2", payload={})
    assert r3.correlation_id != cid
    assert current_correlation_id() is None


def test_nested_correlation_restores_outer_on_inner_exit():
    log = InMemoryAuditLog()

    outer = uuid4()
    inner = uuid4()

    with correlation(outer):
        r_outer_before = log.record("raw_event", event_id="e", payload={})
        with correlation(inner):
            r_inner = log.record("signal", event_id="e", payload={})
        r_outer_after = log.record("intent", event_id="e", payload={})

    assert r_outer_before.correlation_id == outer
    assert r_inner.correlation_id == inner
    assert r_outer_after.correlation_id == outer
    assert current_correlation_id() is None


def test_set_correlation_id_binds_to_current_context():
    cid = uuid4()
    set_correlation_id(cid)
    try:
        assert current_correlation_id() == cid
        log = InMemoryAuditLog()
        rec = log.record("raw_event", event_id="e1", payload={})
        assert rec.correlation_id == cid
    finally:
        # Reset by entering a scoped correlation and letting it overwrite;
        # then leaving the test context — contextvar leaks are bounded to
        # this test function's async context in pytest.
        pass


def test_query_returns_only_matching_correlation_sorted_asc():
    log = InMemoryAuditLog()

    cid_a = uuid4()
    cid_b = uuid4()

    with correlation(cid_a):
        log.record("raw_event", event_id="a1", payload={})
        log.record("signal", event_id="a1", payload={})

    with correlation(cid_b):
        log.record("raw_event", event_id="b1", payload={})

    with correlation(cid_a):
        log.record("intent", event_id="a1", payload={})

    a_records = log.query(correlation_id=cid_a)
    b_records = log.query(correlation_id=cid_b)

    assert [r.stage for r in a_records] == ["raw_event", "signal", "intent"]
    assert all(r.correlation_id == cid_a for r in a_records)
    # Sorted ascending by created_at.
    assert all(
        a_records[i].created_at <= a_records[i + 1].created_at
        for i in range(len(a_records) - 1)
    )

    assert len(b_records) == 1
    assert b_records[0].correlation_id == cid_b


def test_inmemory_record_returns_audit_record_instance():
    log = InMemoryAuditLog()
    rec = log.record("raw_event", event_id="e1", payload={"x": 1})
    assert isinstance(rec, AuditRecord)
    assert rec.stage == "raw_event"
    assert rec.event_id == "e1"
    assert rec.payload == {"x": 1}
    assert log.records[-1] is rec


def test_audit_log_schema_constant():
    assert isinstance(AUDIT_LOG_SCHEMA, str)
    assert AUDIT_LOG_SCHEMA
    assert "audit_log" in AUDIT_LOG_SCHEMA


def test_postgres_record_issues_insert_with_json_encoded_payload():
    """Decimal and datetime in the payload must be JSON-encoded as strings."""
    cursor = MagicMock()
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    cursor_ctx = MagicMock()
    cursor_ctx.__enter__.return_value = cursor
    cursor_ctx.__exit__.return_value = False
    conn.cursor.return_value = cursor_ctx

    ts = datetime(2026, 4, 13, 12, 0, 0, tzinfo=timezone.utc)
    payload = {
        "price": Decimal("101.25"),
        "when": ts,
        "symbol": "AAPL",
    }

    with patch("psycopg.connect", return_value=conn) as connect:
        pg = PostgresAuditLog("postgresql://example/db")
        cid = uuid4()
        with correlation(cid):
            rec = pg.record("order", event_id="cid-1", payload=payload)

    connect.assert_called_once_with("postgresql://example/db")
    cursor.execute.assert_called_once()
    sql, params = cursor.execute.call_args.args
    assert "INSERT INTO audit_log" in sql
    # Params: (id, correlation_id, stage, event_id, payload_json, created_at)
    assert len(params) == 6
    rec_id, corr, stage, event_id, encoded_payload, created_at = params
    assert isinstance(rec_id, UUID)
    assert corr == cid
    assert stage == "order"
    assert event_id == "cid-1"
    assert isinstance(encoded_payload, str)
    decoded = json.loads(encoded_payload)
    # Decimal -> string, datetime -> string (via default=str).
    assert decoded["price"] == "101.25"
    assert decoded["when"] == str(ts)
    assert decoded["symbol"] == "AAPL"
    assert isinstance(created_at, datetime)
    # Returned record reflects the persisted row.
    assert rec.correlation_id == cid
    assert rec.stage == "order"
    assert rec.payload["symbol"] == "AAPL"


def test_postgres_init_schema_executes_schema():
    cursor = MagicMock()
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    cursor_ctx = MagicMock()
    cursor_ctx.__enter__.return_value = cursor
    cursor_ctx.__exit__.return_value = False
    conn.cursor.return_value = cursor_ctx

    with patch("psycopg.connect", return_value=conn):
        pg = PostgresAuditLog("postgresql://example/db")
        pg.init_schema()

    cursor.execute.assert_called_once_with(AUDIT_LOG_SCHEMA)


@pytest.fixture(autouse=True)
def _isolate_correlation_context():
    """Ensure each test starts with no bound correlation id.

    ``set_correlation_id`` does not use a token so we can't reliably reset it
    from within the test; pytest's fixture framework gives each test a fresh
    context-var snapshot via this enter/exit pair."""
    from trading_algo.audit import _correlation

    token = _correlation.set(None)
    try:
        yield
    finally:
        _correlation.reset(token)
