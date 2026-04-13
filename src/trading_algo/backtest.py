from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable

from backtester import (
    HarnessConfig,
    Mode,
    Order as BTOrder,
    OrderSide as BTOrderSide,
    OrderType as BTOrderType,
    RawEvent as BTRawEvent,
    ReplayHarness,
    Report,
    SignalEvent,
    Strategy as BTStrategy,
)
from backtester.strategy import Context
from nlp_signal import EventType, Signal

from trading_algo.strategy import DefaultStrategy, Strategy


class _SignalEventAdapter(BTStrategy):
    """Plugs our Signal → TradeIntent Strategy into the backtester.

    Consumes the backtester's ``SignalEvent`` (pre-extracted signals — typical
    for backtesting, where NLP has already run offline), converts each into an
    ``nlp_signal.Signal``, runs it through the injected Strategy, then
    submits a backtester Order sized against a last-known mark."""

    def __init__(self, strategy: Strategy, fill_price_fallback: float = 100.0) -> None:
        self._strategy = strategy
        self._fallback = fill_price_fallback
        self._last_price: dict[str, float] = {}

    def on_event(self, event: BTRawEvent, ctx: Context) -> None:
        if not isinstance(event, SignalEvent):
            return
        symbol = event.symbol
        if symbol is None:
            return

        signal = _signal_event_to_signal(event, symbol)
        intent = self._strategy.on_signal(signal)
        if intent is None or intent.notional is None:
            return

        mark = self._last_price.get(symbol) or ctx.portfolio.marks.get(symbol) or self._fallback
        qty = float(intent.notional) / float(mark)
        if qty <= 0:
            return

        ctx.broker.submit(
            BTOrder(
                symbol=symbol,
                side=BTOrderSide.BUY if intent.side.value == "buy" else BTOrderSide.SELL,
                qty=qty,
                type=BTOrderType.MARKET,
                client_tag=intent.client_order_id,
            )
        )


def _signal_event_to_signal(event: SignalEvent, symbol: str) -> Signal:
    # SignalEvent.value ∈ [-1, 1] (sentiment-like); clamp to keep the nlp_signal
    # model happy. Magnitude = abs(value), confidence from SignalEvent.
    value = max(-1.0, min(1.0, event.value))
    return Signal(
        source_event_id=f"{symbol}-{event.ts.isoformat()}",
        ticker=symbol,
        event_type=EventType.OTHER,
        score=value,
        magnitude=min(1.0, abs(value)),
        confidence=max(0.0, min(1.0, event.confidence)),
        rationale=event.name or "backtest signal",
        extracted_at=event.ts if event.ts.tzinfo else event.ts.replace(tzinfo=timezone.utc),
    )


@dataclass(frozen=True, slots=True)
class BacktestResult:
    report: Report
    orders_submitted: int


def run_backtest(
    events: Iterable[BTRawEvent],
    *,
    strategy: Strategy | None = None,
    starting_cash: Decimal | float = Decimal("100000"),
) -> BacktestResult:
    """Run the integrated strategy through the backtester harness."""
    from backtester import IterableEventSource, LocalSimBroker

    bt_strategy = _SignalEventAdapter(strategy or DefaultStrategy())
    broker = LocalSimBroker()
    harness = ReplayHarness(
        source=IterableEventSource(list(events)),
        strategy=bt_strategy,
        broker=broker,
        config=HarnessConfig(starting_cash=float(starting_cash), mode=Mode.HISTORICAL),
    )
    report = harness.run()
    total = len(broker.open_orders()) + report.trades.total_fills
    return BacktestResult(report=report, orders_submitted=total)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
