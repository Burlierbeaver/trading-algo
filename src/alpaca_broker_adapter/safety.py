from __future__ import annotations

from decimal import Decimal
from typing import Optional

from .config import Settings
from .errors import SafetyRailViolation
from .models import OrderRequest


def preflight_check(
    order: OrderRequest,
    settings: Settings,
    reference_price: Optional[Decimal] = None,
) -> None:
    """Raise SafetyRailViolation if the order violates any enabled live rail.

    No-op when settings.is_live is False. ``reference_price`` is only needed
    when ``max_notional_per_order`` is enabled and the order specifies ``qty``
    (for notional orders the notional is used directly).
    """
    if not settings.is_live:
        return

    if settings.kill_switch_file and settings.kill_switch_file.exists():
        raise SafetyRailViolation(
            f"kill switch active: {settings.kill_switch_file}"
        )

    whitelist = settings.whitelist_set
    if whitelist is not None and order.symbol.upper() not in whitelist:
        raise SafetyRailViolation(
            f"symbol {order.symbol!r} not in whitelist"
        )

    if settings.max_qty_per_order is not None and order.qty is not None:
        if order.qty > settings.max_qty_per_order:
            raise SafetyRailViolation(
                f"qty {order.qty} exceeds max_qty_per_order={settings.max_qty_per_order}"
            )

    if settings.max_notional_per_order is not None:
        notional = _estimate_notional(order, reference_price)
        if notional is not None and notional > settings.max_notional_per_order:
            raise SafetyRailViolation(
                f"estimated notional {notional} exceeds "
                f"max_notional_per_order={settings.max_notional_per_order}"
            )


def _estimate_notional(
    order: OrderRequest,
    reference_price: Optional[Decimal],
) -> Optional[Decimal]:
    if order.notional is not None:
        return order.notional
    if order.qty is None:
        return None
    # Limit orders have an explicit price; use it.
    if order.limit_price is not None:
        return order.qty * order.limit_price
    if reference_price is not None:
        return order.qty * reference_price
    return None
