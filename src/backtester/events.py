from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class RawEvent:
    ts: datetime
    symbol: str | None = None

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None:
            raise ValueError(f"{type(self).__name__}.ts must be timezone-aware")


@dataclass(frozen=True, slots=True)
class MarketEvent(RawEvent):
    pass


@dataclass(frozen=True, slots=True)
class QuoteEvent(MarketEvent):
    bid: float = 0.0
    ask: float = 0.0
    bid_size: float = 0.0
    ask_size: float = 0.0

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0


@dataclass(frozen=True, slots=True)
class TradeEvent(MarketEvent):
    price: float = 0.0
    size: float = 0.0


@dataclass(frozen=True, slots=True)
class BarEvent(MarketEvent):
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0


@dataclass(frozen=True, slots=True)
class NewsEvent(RawEvent):
    headline: str = ""
    body: str = ""
    source: str = ""
    url: str = ""
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SignalEvent(RawEvent):
    name: str = ""
    value: float = 0.0
    confidence: float = 1.0
    payload: Mapping[str, Any] = field(default_factory=dict)


def parse_ts(value: str | datetime | int | float) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


_EVENT_TYPES: dict[str, type[RawEvent]] = {
    "quote": QuoteEvent,
    "trade": TradeEvent,
    "bar": BarEvent,
    "news": NewsEvent,
    "signal": SignalEvent,
}


def from_dict(d: Mapping[str, Any]) -> RawEvent:
    kind = d.get("type")
    if kind not in _EVENT_TYPES:
        raise ValueError(f"unknown event type: {kind!r}")
    cls = _EVENT_TYPES[kind]
    payload = {k: v for k, v in d.items() if k != "type"}
    if "ts" in payload:
        payload["ts"] = parse_ts(payload["ts"])
    if cls is SignalEvent and "payload" in payload and payload["payload"] is None:
        payload["payload"] = {}
    return cls(**payload)
