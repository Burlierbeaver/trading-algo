from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest


# Ensure src/ is importable when running tests without `pip install -e .`.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from risk_manager.config import PositionCap, RiskConfig, ReconcilerConfig  # noqa: E402
from risk_manager.sectors import SectorClassifier  # noqa: E402
from risk_manager.types import Mode, OrderType, Side, TradeIntent  # noqa: E402


@pytest.fixture
def fixed_now():
    return datetime(2026, 4, 12, 14, 30, tzinfo=timezone.utc)


@pytest.fixture
def clock(fixed_now):
    def _clock():
        return fixed_now
    return _clock


@pytest.fixture
def sectors():
    return SectorClassifier(
        {
            "AAPL": "Technology",
            "MSFT": "Technology",
            "NVDA": "Technology",
            "JPM": "Financials",
            "BAC": "Financials",
            "XOM": "Energy",
            "SPY": "ETF",
        }
    )


@pytest.fixture
def base_config(tmp_path):
    return RiskConfig(
        mode=Mode.BACKTEST,
        workdir=tmp_path,
        db_path=tmp_path / "risk.db",
        sectors_path=tmp_path / "missing-sectors.json",
        max_daily_loss_pct=Decimal("0.02"),
        default_position_cap=PositionCap(Decimal("25000"), Decimal("0.05")),
        symbol_position_caps={
            "AAPL": PositionCap(Decimal("50000"), Decimal("0.10")),
        },
        default_sector_cap_pct=Decimal("0.25"),
        sector_caps_pct={"UNKNOWN": Decimal("0.02")},
        reconciler=ReconcilerConfig(
            interval_seconds=1, qty_tolerance=Decimal("0"), cash_tolerance_pct=Decimal("0.001")
        ),
    )


def make_intent(
    symbol: str = "AAPL",
    side: Side = Side.BUY,
    qty: Decimal | int | None = 1,
    notional: Decimal | int | None = None,
    order_type: OrderType = OrderType.MARKET,
    limit_price: Decimal | None = None,
    strategy_id: str = "default",
    ts: datetime | None = None,
) -> TradeIntent:
    return TradeIntent(
        symbol=symbol,
        side=side,
        order_type=order_type,
        qty=Decimal(qty) if qty is not None else None,
        notional=Decimal(notional) if notional is not None else None,
        limit_price=limit_price,
        strategy_id=strategy_id,
        client_order_id=uuid.uuid4().hex,
        ts=ts or datetime(2026, 4, 12, 14, 30, tzinfo=timezone.utc),
    )
