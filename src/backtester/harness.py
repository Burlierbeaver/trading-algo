from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from .broker import Broker, LocalSimBroker
from .clock import Clock, RealClock, SimClock
from .events import MarketEvent, RawEvent
from .portfolio import Portfolio
from .report import Report, build_report
from .source import EventSource
from .strategy import Context, Strategy


class Mode(str, Enum):
    HISTORICAL = "historical"
    PAPER = "paper"


@dataclass(slots=True)
class HarnessConfig:
    starting_cash: float = 100_000.0
    mode: Mode = Mode.HISTORICAL
    seed: int | None = None


@dataclass(slots=True)
class ReplayHarness:
    source: EventSource
    strategy: Strategy
    broker: Broker = field(default_factory=LocalSimBroker)
    config: HarnessConfig = field(default_factory=HarnessConfig)
    clock: Clock = field(init=False)
    portfolio: Portfolio = field(init=False)
    _equity_curve: list[tuple[str, float]] = field(default_factory=list)
    _observer: Callable[[RawEvent], None] | None = None

    def __post_init__(self) -> None:
        self.clock = SimClock() if self.config.mode is Mode.HISTORICAL else RealClock()
        self.portfolio = Portfolio(cash=self.config.starting_cash)

    def run(self) -> Report:
        ctx = Context(clock=self.clock, portfolio=self.portfolio, broker=self.broker)
        self.strategy.on_start(ctx)

        for event in self.source:
            self.clock.advance_to(event.ts)

            if isinstance(event, MarketEvent) and event.symbol is not None:
                mark = _mark_from_event(event)
                if mark is not None:
                    self.portfolio.update_mark(event.symbol, mark)

            self.strategy.on_event(event, ctx)

            if isinstance(event, MarketEvent):
                for fill in self.broker.on_market_event(event):
                    self.portfolio.apply_fill(fill)
                    self.strategy.on_fill(fill, ctx)

            self._equity_curve.append((event.ts.isoformat(), self.portfolio.equity()))

            if self._observer is not None:
                self._observer(event)

        self.strategy.on_end(ctx)
        return build_report(
            portfolio=self.portfolio,
            equity_curve=self._equity_curve,
            starting_cash=self.config.starting_cash,
            mode=self.config.mode.value,
            seed=self.config.seed,
        )


def _mark_from_event(event: MarketEvent) -> float | None:
    from .events import BarEvent, QuoteEvent, TradeEvent

    if isinstance(event, QuoteEvent):
        return event.mid
    if isinstance(event, TradeEvent):
        return event.price
    if isinstance(event, BarEvent):
        return event.close
    return None
