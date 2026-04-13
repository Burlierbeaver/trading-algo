from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from alpaca_broker_adapter import (
    OrderRequest,
    OrderResult,
    OrderStatus,
)
from nlp_signal import EventType, RawEvent, Signal


class FakeNLP:
    """Deterministic NLP stub that emits one canned Signal per RawEvent — lets
    the pipeline run end-to-end without Anthropic API credentials."""

    def __init__(self, signals: list[Signal] | None = None) -> None:
        self._signals = signals

    async def process(self, event: RawEvent) -> list[Signal]:
        if self._signals is not None:
            return list(self._signals)
        return [
            Signal(
                source_event_id=event.id,
                ticker="AAPL",
                event_type=EventType.EARNINGS_BEAT,
                score=0.8,
                magnitude=0.7,
                confidence=0.9,
                rationale="fake signal for demo",
                extracted_at=datetime.now(timezone.utc),
            )
        ]


class FakeBroker:
    """In-memory broker matching the minimal execute_order contract. Records
    every submitted order; returns immediately-filled terminal results."""

    def __init__(self, fill_price: Decimal = Decimal("150.00")) -> None:
        self._fill_price = fill_price
        self.submitted: list[OrderRequest] = []

    def execute_order(
        self,
        order: OrderRequest,
        *,
        reference_price: Optional[Decimal] = None,
    ) -> OrderResult:
        self.submitted.append(order)
        qty = order.qty
        if qty is None and order.notional is not None:
            qty = (order.notional / self._fill_price).quantize(Decimal("0.0001"))
        return OrderResult(
            client_order_id=order.client_order_id,
            broker_order_id=f"fake-{uuid4().hex[:8]}",
            status=OrderStatus.FILLED,
            submitted_at=datetime.now(timezone.utc),
            filled_qty=qty or Decimal("0"),
            filled_avg_price=self._fill_price,
        )
