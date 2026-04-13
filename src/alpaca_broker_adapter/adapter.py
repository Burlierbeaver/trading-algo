from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Optional
from uuid import UUID

from .client import BrokerClient, normalize_status
from .config import Settings
from .db import OrderRepo
from .errors import ReconciliationTimeout
from .models import Fill, OrderRequest, OrderResult, OrderSide, OrderStatus
from .safety import preflight_check

log = logging.getLogger(__name__)

Clock = Callable[[], float]
Sleeper = Callable[[float], None]


class BrokerAdapter:
    """Submits orders to Alpaca and reconciles fills into Postgres.

    The adapter holds three collaborators:
      * ``settings`` — runtime config (mode, polling tuning, live safety rails)
      * ``client`` — thin broker API wrapper (paper/live transparent)
      * ``repo`` — persistence seam for orders + fills
    """

    def __init__(
        self,
        settings: Settings,
        client: BrokerClient,
        repo: OrderRepo,
        *,
        clock: Clock = time.monotonic,
        sleep: Sleeper = time.sleep,
    ) -> None:
        self.settings = settings
        self.client = client
        self.repo = repo
        self._clock = clock
        self._sleep = sleep

    # ----------------------------------------------------- construction shim

    @classmethod
    def from_env(cls) -> "BrokerAdapter":
        from .client import AlpacaClient
        from .db import PostgresOrderRepo

        settings = Settings()
        client = AlpacaClient(settings)
        repo = PostgresOrderRepo(settings)
        repo.init_schema()
        return cls(settings, client, repo)

    # -------------------------------------------------------------- public

    def execute_order(
        self,
        order: OrderRequest,
        *,
        reference_price: Optional[Decimal] = None,
        wait_for_terminal: bool = True,
    ) -> OrderResult:
        """Preflight-check, submit, persist, and (optionally) poll to terminal."""
        preflight_check(order, self.settings, reference_price)

        self.repo.insert_pending_order(order, self.settings.alpaca_mode.value)

        resp = self.client.submit_order(order)
        broker_order_id = resp["broker_order_id"]
        status = normalize_status(resp["status"])
        self.repo.mark_submitted(order.client_order_id, broker_order_id, status, resp["raw"])

        result = OrderResult(
            client_order_id=order.client_order_id,
            broker_order_id=broker_order_id,
            status=status,
            submitted_at=resp["submitted_at"],
            filled_qty=resp.get("filled_qty") or Decimal("0"),
            filled_avg_price=resp.get("filled_avg_price"),
        )
        if not wait_for_terminal or status.is_terminal:
            if status.is_terminal:
                self._record_fills(broker_order_id, order.symbol, order.side)
            return result

        return self._poll_until_terminal(order, broker_order_id, result)

    def reconcile_pending_orders(self) -> list[OrderResult]:
        """Sweep all non-terminal orders — used by a cron/background worker."""
        results: list[OrderResult] = []
        for row in self.repo.list_non_terminal_orders():
            broker_order_id = row["broker_order_id"]
            symbol = row["symbol"]
            side = OrderSide(row["side"])
            resp = self.client.get_order(broker_order_id)
            result = self._apply_state(broker_order_id, resp, symbol, side)
            results.append(
                OrderResult(
                    client_order_id=UUID(row["client_order_id"]) if isinstance(row["client_order_id"], str) else row["client_order_id"],
                    broker_order_id=broker_order_id,
                    status=result,
                    submitted_at=resp["submitted_at"],
                    filled_qty=resp.get("filled_qty") or Decimal("0"),
                    filled_avg_price=resp.get("filled_avg_price"),
                )
            )
        return results

    # -------------------------------------------------------------- private

    def _poll_until_terminal(
        self,
        order: OrderRequest,
        broker_order_id: str,
        last: OrderResult,
    ) -> OrderResult:
        deadline = self._clock() + self.settings.poll_timeout_s
        interval = self.settings.poll_interval_s

        while True:
            if self._clock() >= deadline:
                log.warning(
                    "reconcile timeout broker_order_id=%s last_status=%s",
                    broker_order_id,
                    last.status.value,
                )
                raise ReconciliationTimeout(
                    f"order {broker_order_id} still {last.status.value} after {self.settings.poll_timeout_s}s"
                )
            self._sleep(interval)
            resp = self.client.get_order(broker_order_id)
            status = self._apply_state(broker_order_id, resp, order.symbol, order.side)
            last = OrderResult(
                client_order_id=order.client_order_id,
                broker_order_id=broker_order_id,
                status=status,
                submitted_at=resp["submitted_at"],
                filled_qty=resp.get("filled_qty") or Decimal("0"),
                filled_avg_price=resp.get("filled_avg_price"),
            )
            if status.is_terminal:
                return last

    def _apply_state(
        self,
        broker_order_id: str,
        resp: dict,
        symbol: str,
        side: OrderSide,
    ) -> OrderStatus:
        status = normalize_status(resp["status"])
        terminal_at = datetime.now(timezone.utc) if status.is_terminal else None
        self.repo.update_order_state(
            broker_order_id=broker_order_id,
            status=status,
            filled_qty=resp.get("filled_qty") or Decimal("0"),
            filled_avg_price=resp.get("filled_avg_price"),
            terminal_at=terminal_at,
            raw=resp["raw"],
        )
        if status.is_terminal:
            self._record_fills(broker_order_id, symbol, side)
        return status

    def _record_fills(self, broker_order_id: str, symbol: str, side: OrderSide) -> None:
        try:
            activities = self.client.get_fills(broker_order_id)
        except Exception:  # fills are best-effort; order state still recorded
            log.exception("get_fills failed broker_order_id=%s", broker_order_id)
            return

        for a in activities:
            fill = Fill(
                broker_order_id=broker_order_id,
                broker_fill_id=a.get("broker_fill_id"),
                symbol=a.get("symbol") or symbol,
                side=OrderSide(a.get("side") or side.value),
                qty=a["qty"],
                price=a["price"],
                filled_at=a["filled_at"],
            )
            self.repo.insert_fill(fill, a.get("raw", {}))
