from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from alpaca_broker_adapter import OrderResult
from nlp_signal import RawEvent, Signal
from risk_manager import Order, Reject, RiskEngine, TradeIntent

from trading_algo.bridges.broker import intent_to_order_request
from trading_algo.strategy import DefaultStrategy, Strategy

log = logging.getLogger(__name__)


class SignalSource(Protocol):
    async def process(self, event: RawEvent) -> list[Signal]: ...


class OrderExecutor(Protocol):
    def execute_order(self, request, *, reference_price: Decimal | None = None) -> OrderResult: ...


@dataclass
class PipelineResult:
    event_id: str
    signals: list[Signal] = field(default_factory=list)
    intents: list[TradeIntent] = field(default_factory=list)
    approved: list[Order] = field(default_factory=list)
    rejected: list[Reject] = field(default_factory=list)
    executed: list[OrderResult] = field(default_factory=list)


class Pipeline:
    """RawEvent → Signals → TradeIntents → Risk-approved Orders → Broker fills.

    Wires the four isolated components together. Each step is swappable:
    inject a different Strategy, a mocked broker, etc."""

    def __init__(
        self,
        nlp: SignalSource,
        risk: RiskEngine,
        broker: OrderExecutor,
        strategy: Strategy | None = None,
    ) -> None:
        self._nlp = nlp
        self._risk = risk
        self._broker = broker
        self._strategy = strategy or DefaultStrategy()

    async def ingest(self, event: RawEvent) -> PipelineResult:
        result = PipelineResult(event_id=event.id)

        result.signals = await self._nlp.process(event)
        log.info("event=%s extracted %d signals", event.id, len(result.signals))

        for signal in result.signals:
            intent = self._strategy.on_signal(signal)
            if intent is None:
                continue
            result.intents.append(intent)

            decision = self._risk.check(intent)
            if isinstance(decision, Order):
                result.approved.append(decision)
                order_result = self._execute(decision)
                if order_result is not None:
                    result.executed.append(order_result)
            else:
                result.rejected.append(decision)
                log.info(
                    "intent %s rejected: rule=%s reason=%s",
                    intent.client_order_id,
                    decision.rule,
                    decision.reason,
                )

        return result

    def _execute(self, order: Order) -> OrderResult | None:
        try:
            request = intent_to_order_request(order)
            return self._broker.execute_order(request)
        except Exception:
            log.exception("broker execute failed for approval_id=%s", order.approval_id)
            return None
