from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Protocol

from .config import Settings
from .errors import BrokerAPIError
from .models import OrderRequest, OrderStatus, OrderType


# ---------------------------------------------------------------------------
# Protocol: the narrow surface the adapter uses.
#
# Every method returns a plain dict with a stable shape so the adapter and
# tests don't need to depend on alpaca-py's model types.
# ---------------------------------------------------------------------------


class BrokerClient(Protocol):
    def submit_order(self, order: OrderRequest) -> dict[str, Any]: ...
    def get_order(self, broker_order_id: str) -> dict[str, Any]: ...
    def get_fills(self, broker_order_id: str) -> list[dict[str, Any]]: ...


# ---------------------------------------------------------------------------
# Alpaca implementation
# ---------------------------------------------------------------------------


_ALPACA_STATUS_MAP: dict[str, OrderStatus] = {
    "new": OrderStatus.SUBMITTED,
    "accepted": OrderStatus.SUBMITTED,
    "pending_new": OrderStatus.SUBMITTED,
    "accepted_for_bidding": OrderStatus.SUBMITTED,
    "held": OrderStatus.SUBMITTED,
    "partially_filled": OrderStatus.PARTIALLY_FILLED,
    "filled": OrderStatus.FILLED,
    "canceled": OrderStatus.CANCELED,
    "pending_cancel": OrderStatus.CANCELED,
    "rejected": OrderStatus.REJECTED,
    "expired": OrderStatus.EXPIRED,
    "done_for_day": OrderStatus.EXPIRED,
}


def normalize_status(raw: str) -> OrderStatus:
    return _ALPACA_STATUS_MAP.get(raw.lower(), OrderStatus.SUBMITTED)


class AlpacaClient:
    """Concrete BrokerClient backed by alpaca-py."""

    def __init__(self, settings: Settings) -> None:
        # Lazy imports keep tests free of the alpaca-py dependency tree.
        from alpaca.trading.client import TradingClient

        if not settings.alpaca_api_key or not settings.alpaca_api_secret:
            raise BrokerAPIError("ALPACA_API_KEY / ALPACA_API_SECRET are required")
        self._trading = TradingClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_api_secret,
            paper=not settings.is_live,
        )

    # -- writes --------------------------------------------------------------

    def submit_order(self, order: OrderRequest) -> dict[str, Any]:
        from alpaca.trading.enums import (
            OrderSide as AlpacaSide,
            TimeInForce as AlpacaTIF,
        )
        from alpaca.trading.requests import (
            LimitOrderRequest,
            MarketOrderRequest,
        )

        side = AlpacaSide(order.side.value)
        tif = AlpacaTIF(order.time_in_force.value)
        common: dict[str, Any] = {
            "symbol": order.symbol,
            "side": side,
            "time_in_force": tif,
            "client_order_id": str(order.client_order_id),
        }
        if order.qty is not None:
            common["qty"] = str(order.qty)
        else:
            common["notional"] = str(order.notional)

        if order.order_type is OrderType.MARKET:
            req = MarketOrderRequest(**common)
        else:
            req = LimitOrderRequest(limit_price=str(order.limit_price), **common)

        try:
            resp = self._trading.submit_order(req)
        except Exception as exc:  # alpaca-py raises APIError for 4xx/5xx
            raise BrokerAPIError(f"submit_order failed: {exc}") from exc
        return _order_to_dict(resp)

    # -- reads ---------------------------------------------------------------

    def get_order(self, broker_order_id: str) -> dict[str, Any]:
        try:
            resp = self._trading.get_order_by_id(broker_order_id)
        except Exception as exc:
            raise BrokerAPIError(f"get_order failed: {exc}") from exc
        return _order_to_dict(resp)

    def get_fills(self, broker_order_id: str) -> list[dict[str, Any]]:
        from alpaca.trading.enums import ActivityType
        from alpaca.trading.requests import GetAccountActivitiesRequest

        try:
            resp = self._trading.get_account_activities(
                GetAccountActivitiesRequest(activity_types=[ActivityType.FILL])
            )
        except Exception as exc:
            raise BrokerAPIError(f"get_fills failed: {exc}") from exc
        return [_activity_to_dict(a) for a in resp if _activity_matches(a, broker_order_id)]


# ---------------------------------------------------------------------------
# Alpaca -> dict normalization
# ---------------------------------------------------------------------------


def _order_to_dict(o: Any) -> dict[str, Any]:
    return {
        "broker_order_id": str(_get(o, "id")),
        "client_order_id": _str_or_none(_get(o, "client_order_id")),
        "status": str(_get(o, "status")).split(".")[-1].lower(),
        "filled_qty": _decimal_or_zero(_get(o, "filled_qty")),
        "filled_avg_price": _decimal_or_none(_get(o, "filled_avg_price")),
        "submitted_at": _datetime_or_now(_get(o, "submitted_at")),
        "raw": _to_jsonable(o),
    }


def _activity_to_dict(a: Any) -> dict[str, Any]:
    return {
        "broker_fill_id": _str_or_none(_get(a, "id")),
        "broker_order_id": _str_or_none(_get(a, "order_id")),
        "symbol": str(_get(a, "symbol") or ""),
        "side": str(_get(a, "side") or "").split(".")[-1].lower(),
        "qty": _decimal_or_zero(_get(a, "qty")),
        "price": _decimal_or_zero(_get(a, "price")),
        "filled_at": _datetime_or_now(_get(a, "transaction_time")),
        "raw": _to_jsonable(a),
    }


def _activity_matches(a: Any, broker_order_id: str) -> bool:
    return _str_or_none(_get(a, "order_id")) == broker_order_id


def _get(obj: Any, attr: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(attr)
    return getattr(obj, attr, None)


def _str_or_none(v: Any) -> str | None:
    if v is None:
        return None
    return str(v)


def _decimal_or_zero(v: Any) -> Decimal:
    if v is None or v == "":
        return Decimal("0")
    return Decimal(str(v))


def _decimal_or_none(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    return Decimal(str(v))


def _datetime_or_now(v: Any) -> datetime:
    if v is None:
        return datetime.now(timezone.utc)
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


def _to_jsonable(obj: Any) -> dict[str, Any]:
    # alpaca-py models expose .model_dump(); fall back to vars() / str().
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(mode="json")
        except Exception:
            pass
    if isinstance(obj, dict):
        return obj
    try:
        return {k: str(v) for k, v in vars(obj).items() if not k.startswith("_")}
    except TypeError:
        return {"repr": str(obj)}


__all__: Iterable[str] = [
    "BrokerClient",
    "AlpacaClient",
    "normalize_status",
]
