from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .portfolio import Portfolio


@dataclass(slots=True)
class TradeSummary:
    total_fills: int
    realized_pnl: float
    unrealized_pnl: float
    net_pnl: float
    win_rate: float
    avg_win: float
    avg_loss: float


@dataclass(slots=True)
class RiskSummary:
    max_drawdown: float
    max_drawdown_pct: float
    sharpe: float
    volatility: float


@dataclass(slots=True)
class Report:
    mode: str
    starting_cash: float
    ending_equity: float
    total_return_pct: float
    trades: TradeSummary
    risk: RiskSummary
    equity_curve: list[tuple[str, float]] = field(default_factory=list)
    fills: list[dict[str, Any]] = field(default_factory=list)
    seed: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    def to_json(self, path: str | Path | None = None, indent: int = 2) -> str:
        text = json.dumps(self.to_dict(), indent=indent, default=str)
        if path is not None:
            Path(path).write_text(text, encoding="utf-8")
        return text


def build_report(
    *,
    portfolio: Portfolio,
    equity_curve: list[tuple[str, float]],
    starting_cash: float,
    mode: str,
    seed: int | None,
) -> Report:
    ending_equity = portfolio.equity()
    total_return_pct = (
        (ending_equity / starting_cash - 1.0) * 100.0 if starting_cash > 0 else 0.0
    )

    trade_pnls = _per_trade_pnls(portfolio)
    wins = [p for p in trade_pnls if p > 0]
    losses = [p for p in trade_pnls if p < 0]
    win_rate = (len(wins) / len(trade_pnls)) if trade_pnls else 0.0
    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(losses) / len(losses)) if losses else 0.0

    equities = [e for _, e in equity_curve]
    max_dd, max_dd_pct = _max_drawdown(equities)
    sharpe, vol = _sharpe_and_vol(equities)

    return Report(
        mode=mode,
        starting_cash=starting_cash,
        ending_equity=ending_equity,
        total_return_pct=total_return_pct,
        trades=TradeSummary(
            total_fills=len(portfolio.fills),
            realized_pnl=portfolio.realized_pnl(),
            unrealized_pnl=portfolio.unrealized_pnl(),
            net_pnl=ending_equity - starting_cash,
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
        ),
        risk=RiskSummary(
            max_drawdown=max_dd,
            max_drawdown_pct=max_dd_pct,
            sharpe=sharpe,
            volatility=vol,
        ),
        equity_curve=equity_curve,
        fills=[_fill_to_dict(f) for f in portfolio.fills],
        seed=seed,
    )


def _per_trade_pnls(portfolio: Portfolio) -> list[float]:
    """Pair each closing fill against the running open lot to produce round-trip P&Ls."""
    lots: dict[str, list[tuple[float, float]]] = {}
    pnls: list[float] = []
    for fill in portfolio.fills:
        lot_stack = lots.setdefault(fill.symbol, [])
        signed_qty = fill.qty if fill.side.value == "buy" else -fill.qty
        qty_left = signed_qty
        while qty_left != 0 and lot_stack and _opposite_sign(lot_stack[-1][0], qty_left):
            open_qty, open_price = lot_stack[-1]
            closing = min(abs(qty_left), abs(open_qty))
            direction = 1.0 if open_qty > 0 else -1.0
            pnls.append(closing * (fill.price - open_price) * direction)
            new_open = open_qty - direction * closing
            qty_left += direction * closing
            if new_open == 0:
                lot_stack.pop()
            else:
                lot_stack[-1] = (new_open, open_price)
        if qty_left != 0:
            lot_stack.append((qty_left, fill.price))
    return pnls


def _opposite_sign(a: float, b: float) -> bool:
    return (a > 0 > b) or (a < 0 < b)


def _max_drawdown(equities: list[float]) -> tuple[float, float]:
    if not equities:
        return 0.0, 0.0
    peak = equities[0]
    max_dd = 0.0
    max_dd_pct = 0.0
    for e in equities:
        if e > peak:
            peak = e
        dd = peak - e
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = (dd / peak * 100.0) if peak > 0 else 0.0
    return max_dd, max_dd_pct


def _sharpe_and_vol(equities: list[float]) -> tuple[float, float]:
    if len(equities) < 2:
        return 0.0, 0.0
    returns: list[float] = []
    for prev, curr in zip(equities, equities[1:]):
        if prev == 0:
            continue
        returns.append((curr - prev) / prev)
    if len(returns) < 2:
        return 0.0, 0.0
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var)
    sharpe = (mean / std * math.sqrt(len(returns))) if std > 0 else 0.0
    return sharpe, std


def _fill_to_dict(fill: Any) -> dict[str, Any]:
    return {
        "order_id": fill.order_id,
        "symbol": fill.symbol,
        "side": fill.side.value,
        "qty": fill.qty,
        "price": fill.price,
        "ts": fill.ts.isoformat(),
        "fee": fill.fee,
    }
