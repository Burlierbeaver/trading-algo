from datetime import datetime, timezone
from decimal import Decimal

import pytest

from alpaca_broker_adapter.errors import (
    ReconciliationTimeout,
    SafetyRailViolation,
)
from alpaca_broker_adapter.models import (
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
)


def _req(**kw) -> OrderRequest:
    return OrderRequest(
        symbol=kw.pop("symbol", "AAPL"),
        side=kw.pop("side", OrderSide.BUY),
        qty=kw.pop("qty", Decimal("1")),
        **kw,
    )


# ----------------------------------------------------------------- submission


def test_execute_order_happy_path_immediately_terminal(
    paper_settings, fake_client, fake_repo, build_adapter
):
    fake_client.submit_status_sequence = ["filled"]
    fake_client.set_fills(
        {
            "broker_fill_id": "fill-1",
            "symbol": "AAPL",
            "side": "buy",
            "qty": Decimal("1"),
            "price": Decimal("150"),
            "filled_at": datetime.now(timezone.utc),
            "raw": {"a": 1},
        }
    )
    adapter = build_adapter(paper_settings)

    result = adapter.execute_order(_req())

    assert result.status is OrderStatus.FILLED
    assert result.broker_order_id
    # order row persists with broker id + terminal status
    row = fake_repo.get_order_by_client_id(result.client_order_id)
    assert row["broker_order_id"] == result.broker_order_id
    assert row["status"] == OrderStatus.FILLED.value
    # fill was recorded
    assert len(fake_repo.fills) == 1
    assert fake_repo.fills[0]["broker_fill_id"] == "fill-1"
    assert fake_repo.fills[0]["broker_order_id"] == result.broker_order_id


def test_execute_order_polls_until_terminal(
    paper_settings, fake_client, fake_repo, build_adapter
):
    # Submit as "accepted", then three polls: new -> partially_filled -> filled
    fake_client.submit_status_sequence = ["accepted"]
    fake_client.queue_get_statuses("new", "partially_filled", "filled")
    fake_client.set_fills(
        {
            "broker_fill_id": "fill-1",
            "symbol": "AAPL",
            "side": "buy",
            "qty": Decimal("1"),
            "price": Decimal("151"),
            "filled_at": datetime.now(timezone.utc),
            "raw": {},
        }
    )
    adapter = build_adapter(paper_settings)

    result = adapter.execute_order(_req())

    assert result.status is OrderStatus.FILLED
    assert result.filled_qty == Decimal("1")
    assert result.filled_avg_price == Decimal("100")  # fake client's get_order price
    assert len(fake_repo.fills) == 1


def test_execute_order_raises_reconciliation_timeout(
    paper_settings, fake_client, build_adapter
):
    fake_client.submit_status_sequence = ["accepted"]
    # Every poll stays "new" — loop exhausts the timeout.
    fake_client.get_status_sequence = []  # default is "filled"; override in method below
    # We want the poll loop to see "new" indefinitely; monkey-patch get_order.
    fake_client.queue_get_statuses(*(["new"] * 100))
    adapter = build_adapter(paper_settings)

    with pytest.raises(ReconciliationTimeout):
        adapter.execute_order(_req())


def test_execute_order_wait_for_terminal_false_returns_after_submit(
    paper_settings, fake_client, fake_repo, build_adapter
):
    fake_client.submit_status_sequence = ["accepted"]
    adapter = build_adapter(paper_settings)

    result = adapter.execute_order(_req(), wait_for_terminal=False)

    assert result.status is OrderStatus.SUBMITTED
    # no fills recorded (not terminal yet)
    assert fake_repo.fills == []
    # order row exists and is marked submitted
    row = fake_repo.get_order_by_client_id(result.client_order_id)
    assert row["status"] == OrderStatus.SUBMITTED.value


# ------------------------------------------------------------ safety rail path


def test_live_rail_violation_does_not_persist_order_or_submit(
    live_settings, fake_client, fake_repo, build_adapter
):
    live_settings.max_qty_per_order = Decimal("1")
    adapter = build_adapter(live_settings)

    with pytest.raises(SafetyRailViolation):
        adapter.execute_order(_req(qty=Decimal("99")))

    assert fake_client.submitted == []
    assert fake_repo.orders == {}


def test_live_kill_switch_blocks_submit(
    tmp_path, live_settings, fake_client, fake_repo, build_adapter
):
    kill = tmp_path / "KILL"
    kill.write_text("x")
    live_settings.kill_switch_file = kill
    adapter = build_adapter(live_settings)

    with pytest.raises(SafetyRailViolation):
        adapter.execute_order(_req())

    assert fake_client.submitted == []


# ------------------------------------------------------------ reconciliation


def test_reconcile_pending_orders_updates_and_records_fills(
    paper_settings, fake_client, fake_repo, build_adapter
):
    # Submit but don't wait -> row ends up in non-terminal state.
    fake_client.submit_status_sequence = ["accepted"]
    adapter = build_adapter(paper_settings)
    result = adapter.execute_order(_req(), wait_for_terminal=False)

    # Now the order is "submitted" in the repo. Simulate broker reaching terminal.
    fake_client.queue_get_statuses("filled")
    fake_client.set_fills(
        {
            "broker_fill_id": "fill-r",
            "symbol": "AAPL",
            "side": "buy",
            "qty": Decimal("1"),
            "price": Decimal("100"),
            "filled_at": datetime.now(timezone.utc),
            "raw": {},
        }
    )

    results = adapter.reconcile_pending_orders()

    assert len(results) == 1
    assert results[0].status is OrderStatus.FILLED
    row = fake_repo.get_order_by_client_id(result.client_order_id)
    assert row["status"] == OrderStatus.FILLED.value
    assert any(f["broker_fill_id"] == "fill-r" for f in fake_repo.fills)


def test_reconcile_skips_terminal_orders(
    paper_settings, fake_client, fake_repo, build_adapter
):
    fake_client.submit_status_sequence = ["filled"]
    fake_client.set_fills()
    adapter = build_adapter(paper_settings)
    adapter.execute_order(_req())

    # Nothing non-terminal remains.
    assert adapter.reconcile_pending_orders() == []


# ---------------------------------------------------------------- idempotency


def test_each_submit_gets_unique_client_order_id(
    paper_settings, fake_client, fake_repo, build_adapter
):
    fake_client.submit_status_sequence = ["filled", "filled"]
    fake_client.set_fills()
    adapter = build_adapter(paper_settings)
    r1 = adapter.execute_order(_req())
    r2 = adapter.execute_order(_req())
    assert r1.client_order_id != r2.client_order_id
    assert len(fake_client.submitted) == 2


def test_explicit_client_order_id_is_respected(
    paper_settings, fake_client, fake_repo, build_adapter
):
    from uuid import uuid4

    fixed = uuid4()
    fake_client.submit_status_sequence = ["filled"]
    fake_client.set_fills()
    adapter = build_adapter(paper_settings)

    result = adapter.execute_order(_req(client_order_id=fixed))

    assert result.client_order_id == fixed
    assert fake_client.submitted[0].client_order_id == fixed


# --------------------------------------------------------------- limit orders


def test_limit_order_flows_through(
    paper_settings, fake_client, fake_repo, build_adapter
):
    fake_client.submit_status_sequence = ["filled"]
    fake_client.set_fills()
    adapter = build_adapter(paper_settings)

    result = adapter.execute_order(
        _req(order_type=OrderType.LIMIT, limit_price=Decimal("100"))
    )

    assert result.status is OrderStatus.FILLED
    submitted = fake_client.submitted[0]
    assert submitted.order_type is OrderType.LIMIT
    assert submitted.limit_price == Decimal("100")
