from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Optional
from uuid import UUID

import pytest

from alpaca_broker_adapter.config import Settings, TradingMode
from alpaca_broker_adapter.models import Fill, OrderRequest, OrderStatus


# ---------------------------------------------------------------- FakeBrokerClient


class FakeBrokerClient:
    """Deterministic stand-in for the real Alpaca client.

    The script can be driven in two ways:
      - ``submit_status_sequence`` / ``get_status_sequence``: pop the next
        status for each call (lets tests simulate new -> filled transitions).
      - ``fills``: returned by ``get_fills`` for any order id.
    """

    def __init__(self) -> None:
        self.submitted: list[OrderRequest] = []
        self.submit_status_sequence: list[str] = ["accepted"]
        self.get_status_sequence: list[str] = []  # consumed per poll
        self.fills: list[dict[str, Any]] = []
        self.raise_on_submit: Optional[Exception] = None
        self._next_broker_id = 1

    # submit ---------------------------------------------------------------

    def submit_order(self, order: OrderRequest) -> dict[str, Any]:
        if self.raise_on_submit is not None:
            raise self.raise_on_submit
        self.submitted.append(order)
        status = self._pop(self.submit_status_sequence, default="accepted")
        broker_order_id = f"broker-{self._next_broker_id}"
        self._next_broker_id += 1
        return {
            "broker_order_id": broker_order_id,
            "client_order_id": str(order.client_order_id),
            "status": status,
            "filled_qty": Decimal("0"),
            "filled_avg_price": None,
            "submitted_at": datetime.now(timezone.utc),
            "raw": {"source": "fake", "status": status},
        }

    # get ------------------------------------------------------------------

    def get_order(self, broker_order_id: str) -> dict[str, Any]:
        status = self._pop(self.get_status_sequence, default="filled")
        filled_qty = Decimal("0")
        filled_avg_price: Optional[Decimal] = None
        if status in ("filled", "partially_filled"):
            filled_qty = Decimal("1")
            filled_avg_price = Decimal("100")
        return {
            "broker_order_id": broker_order_id,
            "client_order_id": None,
            "status": status,
            "filled_qty": filled_qty,
            "filled_avg_price": filled_avg_price,
            "submitted_at": datetime.now(timezone.utc),
            "raw": {"source": "fake", "status": status, "broker_order_id": broker_order_id},
        }

    def get_fills(self, broker_order_id: str) -> list[dict[str, Any]]:
        return [f | {"broker_order_id": broker_order_id} for f in self.fills]

    # helpers --------------------------------------------------------------

    def queue_get_statuses(self, *statuses: str) -> None:
        self.get_status_sequence = list(statuses)

    def set_fills(self, *fills: dict[str, Any]) -> None:
        self.fills = list(fills)

    @staticmethod
    def _pop(seq: list[str], *, default: str) -> str:
        if seq:
            return seq.pop(0)
        return default


# -------------------------------------------------------------------- FakeRepo


class FakeOrderRepo:
    """In-memory OrderRepo that mirrors the Postgres schema just closely
    enough for adapter tests."""

    def __init__(self) -> None:
        self.orders: dict[str, dict[str, Any]] = {}  # key = client_order_id
        self.fills: list[dict[str, Any]] = []
        self.schema_initialized = False

    def init_schema(self) -> None:
        self.schema_initialized = True

    def insert_pending_order(self, order: OrderRequest, mode: str) -> None:
        key = str(order.client_order_id)
        self.orders.setdefault(
            key,
            {
                "client_order_id": key,
                "broker_order_id": None,
                "symbol": order.symbol,
                "side": order.side.value,
                "qty": order.qty,
                "notional": order.notional,
                "order_type": order.order_type.value,
                "limit_price": order.limit_price,
                "time_in_force": order.time_in_force.value,
                "status": OrderStatus.PENDING.value,
                "filled_qty": Decimal("0"),
                "filled_avg_price": None,
                "submitted_at": datetime.now(timezone.utc),
                "terminal_at": None,
                "mode": mode,
                "raw": None,
            },
        )

    def mark_submitted(
        self,
        client_order_id: UUID,
        broker_order_id: str,
        status: OrderStatus,
        raw: dict[str, Any],
    ) -> None:
        row = self.orders[str(client_order_id)]
        row["broker_order_id"] = broker_order_id
        row["status"] = status.value
        row["raw"] = raw

    def update_order_state(
        self,
        broker_order_id: str,
        status: OrderStatus,
        filled_qty: Decimal,
        filled_avg_price: Optional[Decimal],
        terminal_at: Optional[datetime],
        raw: dict[str, Any],
    ) -> None:
        row = self._find_by_broker_id(broker_order_id)
        row["status"] = status.value
        row["filled_qty"] = filled_qty
        row["filled_avg_price"] = filled_avg_price
        if row["terminal_at"] is None and terminal_at is not None:
            row["terminal_at"] = terminal_at
        row["raw"] = raw

    def insert_fill(self, fill: Fill, raw: dict[str, Any]) -> None:
        if fill.broker_fill_id and any(f["broker_fill_id"] == fill.broker_fill_id for f in self.fills):
            return
        self.fills.append(
            {
                "broker_order_id": fill.broker_order_id,
                "broker_fill_id": fill.broker_fill_id,
                "symbol": fill.symbol,
                "side": fill.side.value,
                "qty": fill.qty,
                "price": fill.price,
                "filled_at": fill.filled_at,
                "raw": raw,
            }
        )

    def list_non_terminal_orders(self) -> list[dict[str, Any]]:
        terminal = {s.value for s in OrderStatus if s.is_terminal}
        return [
            dict(row)
            for row in self.orders.values()
            if row["broker_order_id"] is not None and row["status"] not in terminal
        ]

    def get_order_by_client_id(self, client_order_id: UUID) -> Optional[dict[str, Any]]:
        return self.orders.get(str(client_order_id))

    # helper ---------------------------------------------------------------

    def _find_by_broker_id(self, broker_order_id: str) -> dict[str, Any]:
        for row in self.orders.values():
            if row["broker_order_id"] == broker_order_id:
                return row
        raise KeyError(broker_order_id)


# --------------------------------------------------------------------- Clocks


class FakeClock:
    """Monotonic-ish clock driven by calls to ``sleep``."""

    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


# ------------------------------------------------------------------- fixtures


@pytest.fixture
def paper_settings() -> Settings:
    return Settings(
        alpaca_mode=TradingMode.PAPER,
        alpaca_api_key="test",
        alpaca_api_secret="test",
        database_url="postgresql://unused",
        poll_interval_s=0.1,
        poll_timeout_s=1.0,
    )


@pytest.fixture
def live_settings() -> Settings:
    return Settings(
        alpaca_mode=TradingMode.LIVE,
        alpaca_api_key="test",
        alpaca_api_secret="test",
        database_url="postgresql://unused",
        poll_interval_s=0.1,
        poll_timeout_s=1.0,
    )


@pytest.fixture
def fake_client() -> FakeBrokerClient:
    return FakeBrokerClient()


@pytest.fixture
def fake_repo() -> FakeOrderRepo:
    return FakeOrderRepo()


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def build_adapter(
    fake_client: FakeBrokerClient,
    fake_repo: FakeOrderRepo,
    fake_clock: FakeClock,
) -> Callable[..., Any]:
    from alpaca_broker_adapter.adapter import BrokerAdapter

    def _build(settings: Settings):
        return BrokerAdapter(
            settings=settings,
            client=fake_client,
            repo=fake_repo,
            clock=fake_clock.now,
            sleep=fake_clock.sleep,
        )

    return _build
