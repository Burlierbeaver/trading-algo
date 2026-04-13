from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from ..types import Position


class BrokerError(Exception):
    """Raised when the broker adapter fails to serve a request."""


class BrokerAdapter(Protocol):
    """Read-only interface used by the reconciler and for mark-to-market.

    Order submission is the downstream broker adapter worktree's responsibility
    — the risk manager only needs to read state for reconciliation and optional
    price lookups.
    """

    def get_cash(self) -> Decimal: ...

    def get_positions(self) -> dict[str, Position]: ...

    def get_quote(self, symbol: str) -> Decimal: ...
