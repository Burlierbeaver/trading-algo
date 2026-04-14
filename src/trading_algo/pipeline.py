from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from alpaca_broker_adapter import OrderResult
from nlp_signal import RawEvent, Signal
from risk_manager import Order, Reject, RiskEngine, TradeIntent

from trading_algo.alerting import Alert, Alerter, Severity
from trading_algo.audit import AuditLog, correlation
from trading_algo.bridges.broker import intent_to_order_request
from trading_algo.killswitch import KillSwitch
from trading_algo.market_hours import MarketClock, Session
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
    halted: bool = False  # True when market-closed or killswitch blocked execution


class Pipeline:
    """RawEvent → Signals → TradeIntents → Risk-approved Orders → Broker fills.

    Wires the four isolated components together. Each step is swappable:
    inject a different Strategy, a mocked broker, etc. Operational hooks
    (market clock, killswitch, alerting, audit) are all optional — a
    ``Pipeline(nlp, risk, broker)`` behaves as a pure data flow."""

    def __init__(
        self,
        nlp: SignalSource,
        risk: RiskEngine,
        broker: OrderExecutor,
        strategy: Strategy | None = None,
        *,
        clock: MarketClock | None = None,
        killswitch: KillSwitch | None = None,
        alerter: Alerter | None = None,
        audit: AuditLog | None = None,
        allow_extended_hours: bool = False,
    ) -> None:
        self._nlp = nlp
        self._risk = risk
        self._broker = broker
        self._strategy = strategy or DefaultStrategy()
        self._clock = clock
        self._killswitch = killswitch
        self._alerter = alerter
        self._audit = audit
        self._allow_extended_hours = allow_extended_hours

    async def ingest(self, event: RawEvent) -> PipelineResult:
        with correlation() as cid:
            self._record("raw_event", event.id, {"id": event.id, "correlation_id": str(cid)})
            return await self._ingest(event)

    async def _ingest(self, event: RawEvent) -> PipelineResult:
        result = PipelineResult(event_id=event.id)

        if self._clock is not None and not self._clock.is_open(
            allow_extended=self._allow_extended_hours
        ):
            session = self._clock.session()
            log.info("event=%s market closed (session=%s), skipping", event.id, session.value)
            self._record("market_closed", event.id, {"session": session.value})
            result.halted = True
            return result

        result.signals = await self._nlp.process(event)
        log.info("event=%s extracted %d signals", event.id, len(result.signals))
        for signal in result.signals:
            self._record(
                "signal",
                event.id,
                {
                    "ticker": signal.ticker,
                    "event_type": str(signal.event_type),
                    "score": signal.score,
                    "magnitude": signal.magnitude,
                    "confidence": signal.confidence,
                },
            )

        for signal in result.signals:
            intent = self._strategy.on_signal(signal)
            if intent is None:
                continue
            result.intents.append(intent)
            self._record(
                "intent",
                intent.client_order_id,
                {"symbol": intent.symbol, "side": intent.side, "notional": str(intent.notional)},
            )

            decision = self._risk.check(intent)
            if isinstance(decision, Order):
                result.approved.append(decision)
                self._record(
                    "order",
                    decision.approval_id,
                    {
                        "symbol": decision.intent.symbol,
                        "side": decision.intent.side,
                        "qty": str(decision.intent.qty) if decision.intent.qty is not None else None,
                    },
                )
                if self._killswitch is not None and not self._killswitch.is_enabled():
                    log.warning(
                        "event=%s killswitch tripped, skipping execution approval_id=%s",
                        event.id,
                        decision.approval_id,
                    )
                    self._record("killswitch", decision.approval_id, {"skipped": True})
                    self._notify(
                        Severity.CRITICAL,
                        "killswitch_tripped",
                        {"event_id": event.id, "approval_id": decision.approval_id},
                    )
                    result.halted = True
                    continue
                order_result = self._execute(decision)
                if order_result is not None:
                    result.executed.append(order_result)
                    self._record(
                        "fill",
                        order_result.client_order_id,
                        {
                            "symbol": decision.intent.symbol,
                            "filled_qty": str(order_result.filled_qty),
                            "filled_price": str(order_result.filled_avg_price),
                            "status": order_result.status,
                        },
                    )
                    self._notify(
                        Severity.INFO,
                        "fill",
                        {
                            "symbol": decision.intent.symbol,
                            "qty": str(order_result.filled_qty),
                            "price": str(order_result.filled_avg_price),
                        },
                    )
            else:
                result.rejected.append(decision)
                log.info(
                    "intent %s rejected: rule=%s reason=%s",
                    intent.client_order_id,
                    decision.rule,
                    decision.reason,
                )
                self._record(
                    "reject",
                    intent.client_order_id,
                    {"rule": decision.rule, "reason": decision.reason},
                )
                self._notify(
                    Severity.WARNING,
                    "risk_reject",
                    {"intent": intent.client_order_id, "rule": decision.rule, "reason": decision.reason},
                )

        return result

    def _execute(self, order: Order) -> OrderResult | None:
        try:
            request = intent_to_order_request(order)
            return self._broker.execute_order(request)
        except Exception:
            log.exception("broker execute failed for approval_id=%s", order.approval_id)
            return None

    def _record(self, stage: str, event_id: str | None, payload: dict) -> None:
        if self._audit is None:
            return
        try:
            self._audit.record(stage, event_id=event_id, payload=payload)
        except Exception:
            log.exception("audit record failed stage=%s event_id=%s", stage, event_id)

    def _notify(self, severity: Severity, event: str, detail: dict) -> None:
        if self._alerter is None:
            return
        try:
            self._alerter.notify(Alert(severity=severity, event=event, detail=detail))
        except Exception:
            log.exception("alerter notify failed event=%s", event)
