from __future__ import annotations

from decimal import Decimal

from ..types import Position


class SimulatedBroker:
    """In-memory broker backend for backtests and tests.

    Holds its own positions + cash, plus a quote table. Reconciliation against
    this broker will always match its own state — for drift testing use the
    `set_drift` helper to intentionally desynchronize from the ledger.
    """

    def __init__(
        self,
        starting_cash: Decimal = Decimal("100000"),
        positions: dict[str, Position] | None = None,
        quotes: dict[str, Decimal] | None = None,
    ) -> None:
        self._cash = starting_cash
        self._positions: dict[str, Position] = dict(positions or {})
        self._quotes: dict[str, Decimal] = dict(quotes or {})

    def set_cash(self, amount: Decimal) -> None:
        self._cash = amount

    def set_position(self, pos: Position) -> None:
        self._positions[pos.symbol.upper()] = pos

    def set_quote(self, symbol: str, price: Decimal) -> None:
        self._quotes[symbol.upper()] = price

    def set_quotes(self, prices: dict[str, Decimal]) -> None:
        for sym, price in prices.items():
            self._quotes[sym.upper()] = price

    def get_cash(self) -> Decimal:
        return self._cash

    def get_positions(self) -> dict[str, Position]:
        return {s: p for s, p in self._positions.items() if p.qty != 0}

    def get_quote(self, symbol: str) -> Decimal:
        sym = symbol.upper()
        if sym not in self._quotes:
            raise KeyError(f"no quote for {sym}")
        return self._quotes[sym]
