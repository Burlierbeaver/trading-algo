from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Protocol

from .events import MarketEvent, QuoteEvent, TradeEvent, BarEvent
from .portfolio import Fill
from .strategy import Order, OrderSide, OrderType, TimeInForce


class Broker(Protocol):
    def submit(self, order: Order) -> str: ...
    def cancel(self, order_id: str) -> bool: ...
    def on_market_event(self, event: MarketEvent) -> Iterable[Fill]: ...
    def open_orders(self) -> list[Order]: ...


@dataclass(slots=True)
class FillConfig:
    slippage_bps: float = 0.0
    latency_events: int = 0
    fee_per_share: float = 0.0
    allow_partial: bool = False


@dataclass(slots=True)
class _PendingOrder:
    order: Order
    activates_after: int = 0


@dataclass(slots=True)
class LocalSimBroker:
    config: FillConfig = field(default_factory=FillConfig)
    _pending: deque[_PendingOrder] = field(default_factory=deque)
    _seen_events: int = 0

    def submit(self, order: Order) -> str:
        self._pending.append(
            _PendingOrder(order=order, activates_after=self._seen_events + self.config.latency_events)
        )
        return order.id

    def cancel(self, order_id: str) -> bool:
        for i, p in enumerate(self._pending):
            if p.order.id == order_id:
                del self._pending[i]
                return True
        return False

    def open_orders(self) -> list[Order]:
        return [p.order for p in self._pending]

    def on_market_event(self, event: MarketEvent) -> list[Fill]:
        self._seen_events += 1
        fills: list[Fill] = []
        remaining: deque[_PendingOrder] = deque()
        while self._pending:
            pending = self._pending.popleft()
            if pending.activates_after >= self._seen_events:
                remaining.append(pending)
                continue
            if pending.order.symbol != event.symbol:
                remaining.append(pending)
                continue
            fill = self._try_fill(pending.order, event)
            if fill is not None:
                fills.append(fill)
            elif pending.order.tif is not TimeInForce.IOC:
                remaining.append(pending)
        self._pending = remaining
        return fills

    def _try_fill(self, order: Order, event: MarketEvent) -> Fill | None:
        price = self._match_price(order, event)
        if price is None:
            return None
        price = _apply_slippage(price, order.side, self.config.slippage_bps)
        fee = order.qty * self.config.fee_per_share
        return Fill(
            order_id=order.id,
            symbol=order.symbol,
            side=order.side,
            qty=order.qty,
            price=price,
            ts=event.ts,
            fee=fee,
        )

    def _match_price(self, order: Order, event: MarketEvent) -> float | None:
        ref = _reference_price(event, order.side)
        if ref is None:
            return None
        if order.type is OrderType.MARKET:
            return ref
        assert order.limit_price is not None
        if order.side is OrderSide.BUY and ref <= order.limit_price:
            return min(ref, order.limit_price)
        if order.side is OrderSide.SELL and ref >= order.limit_price:
            return max(ref, order.limit_price)
        return None


def _reference_price(event: MarketEvent, side: OrderSide) -> float | None:
    if isinstance(event, QuoteEvent):
        return event.ask if side is OrderSide.BUY else event.bid
    if isinstance(event, TradeEvent):
        return event.price
    if isinstance(event, BarEvent):
        return event.close
    return None


def _apply_slippage(price: float, side: OrderSide, bps: float) -> float:
    if bps == 0:
        return price
    adj = price * bps / 10_000
    return price + adj if side is OrderSide.BUY else price - adj


class AlpacaPaperBroker:
    """Routes orders to Alpaca's paper-trading endpoint.

    The concrete wiring lives in the alpaca-broker-adapter branch; this class
    holds the seam so the harness can switch brokers without code changes.
    """

    def __init__(self, api_key: str, api_secret: str, base_url: str = "https://paper-api.alpaca.markets") -> None:
        try:
            from alpaca.trading.client import TradingClient
        except ImportError as e:
            raise RuntimeError(
                "alpaca-py is required for AlpacaPaperBroker (install extras: backtester[alpaca])"
            ) from e
        self._client = TradingClient(api_key, api_secret, paper=True)
        self._base_url = base_url

    def submit(self, order: Order) -> str:
        raise NotImplementedError("concrete submit lives in alpaca-broker-adapter branch")

    def cancel(self, order_id: str) -> bool:
        raise NotImplementedError

    def on_market_event(self, event: MarketEvent) -> list[Fill]:
        return []

    def open_orders(self) -> list[Order]:
        return []
