from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from risk_manager.rules import (
    DailyLossRule,
    KillSwitchRule,
    PositionCapRule,
    SectorExposureRule,
)
from risk_manager.rules.base import RuleContext
from risk_manager.types import PortfolioSnapshot, Position, Side

from conftest import make_intent


D = Decimal


def _ctx(
    config,
    sectors,
    intent,
    snapshot,
    ref_price=Decimal("100"),
    post_qty=Decimal("10"),
    kill_tripped=False,
    kill_reason=None,
):
    return RuleContext(
        intent=intent,
        snapshot=snapshot,
        ref_price=ref_price,
        post_qty=post_qty,
        config=config,
        sectors=sectors,
        kill_tripped=kill_tripped,
        kill_reason=kill_reason,
    )


def _snap(
    cash=Decimal("100000"),
    positions=None,
    marks=None,
    sod_equity=Decimal("100000"),
):
    return PortfolioSnapshot(
        ts=datetime(2026, 4, 12, 14, 30, tzinfo=timezone.utc),
        cash=cash,
        positions=positions or {},
        marks=marks or {},
        sod_equity=sod_equity,
    )


# ── KillSwitchRule ────────────────────────────────────────────────────
def test_kill_switch_rejects_when_tripped(base_config, sectors):
    intent = make_intent()
    ctx = _ctx(base_config, sectors, intent, _snap(), kill_tripped=True, kill_reason="boom")
    result = KillSwitchRule().evaluate(ctx)
    assert result.rejected
    assert "boom" in (result.reason or "")


def test_kill_switch_passes_when_not_tripped(base_config, sectors):
    ctx = _ctx(base_config, sectors, make_intent(), _snap())
    assert not KillSwitchRule().evaluate(ctx).rejected


# ── PositionCapRule ───────────────────────────────────────────────────
def test_position_cap_rejects_absolute_notional(base_config, sectors):
    intent = make_intent(symbol="MSFT", qty=300)
    # 300 * 100 = 30,000 > default 25,000
    ctx = _ctx(base_config, sectors, intent, _snap(), post_qty=Decimal("300"))
    result = PositionCapRule().evaluate(ctx)
    assert result.rejected
    assert "max_notional" in (result.reason or "")


def test_position_cap_rejects_pct_equity(base_config, sectors):
    intent = make_intent(symbol="MSFT", qty=60)
    # 60 * 100 = 6,000 = 6% of 100k equity (default pct cap = 5%)
    # 6,000 < 25,000 absolute cap, so pct triggers
    ctx = _ctx(base_config, sectors, intent, _snap(), post_qty=Decimal("60"))
    result = PositionCapRule().evaluate(ctx)
    assert result.rejected
    assert "of equity" in (result.reason or "")


def test_position_cap_uses_symbol_override(base_config, sectors):
    # AAPL cap: 50k absolute, 10% pct equity. 80 shares * 100 = 8k (8% of 100k)
    # — passes both. Default cap (MSFT, etc.) would reject 8k (>5%).
    intent = make_intent(symbol="AAPL", qty=80)
    ctx = _ctx(base_config, sectors, intent, _snap(), post_qty=Decimal("80"))
    result = PositionCapRule().evaluate(ctx)
    assert not result.rejected
    # Same size on a default-capped symbol gets rejected on pct equity.
    intent2 = make_intent(symbol="MSFT", qty=80)
    ctx2 = _ctx(base_config, sectors, intent2, _snap(), post_qty=Decimal("80"))
    assert PositionCapRule().evaluate(ctx2).rejected


def test_position_cap_rejects_without_reference_price(base_config, sectors):
    intent = make_intent(symbol="MSFT", qty=10)
    ctx = _ctx(base_config, sectors, intent, _snap(), ref_price=None, post_qty=Decimal("10"))
    result = PositionCapRule().evaluate(ctx)
    assert result.rejected


# ── SectorExposureRule ────────────────────────────────────────────────
def test_sector_exposure_rejects_when_post_trade_exceeds_cap(base_config, sectors):
    # Cash 80k + MSFT 200@100 = equity 100k. Post-trade adds AAPL 200@100 = 20k Tech.
    # Total Tech = 40k / equity 100k = 40% > 25% default cap.
    existing = {"MSFT": Position("MSFT", D("200"), D("100"))}
    marks = {"MSFT": D("100")}
    snap = _snap(cash=D("80000"), positions=existing, marks=marks)
    intent = make_intent(symbol="AAPL", qty=200)
    ctx = _ctx(
        base_config,
        sectors,
        intent,
        snap,
        ref_price=D("100"),
        post_qty=D("200"),
    )
    result = SectorExposureRule().evaluate(ctx)
    assert result.rejected
    assert "Technology" in (result.reason or "")


def test_sector_exposure_allows_cross_sector_positions(base_config, sectors):
    existing = {"MSFT": Position("MSFT", D("200"), D("100"))}
    marks = {"MSFT": D("100")}
    snap = _snap(positions=existing, marks=marks)
    intent = make_intent(symbol="JPM", qty=100)  # Financials
    ctx = _ctx(
        base_config,
        sectors,
        intent,
        snap,
        ref_price=D("100"),
        post_qty=D("100"),
    )
    result = SectorExposureRule().evaluate(ctx)
    assert not result.rejected


def test_sector_exposure_unknown_symbol_uses_unknown_cap(base_config, sectors):
    # UNKNOWN cap is 2% of 100k = 2,000. 30 * 100 = 3,000 exceeds.
    intent = make_intent(symbol="ZZZ", qty=30)
    ctx = _ctx(
        base_config,
        sectors,
        intent,
        _snap(),
        ref_price=D("100"),
        post_qty=D("30"),
    )
    result = SectorExposureRule().evaluate(ctx)
    assert result.rejected
    assert "UNKNOWN" in (result.reason or "")


def test_sector_exposure_reject_unknown_when_configured(base_config, sectors):
    import dataclasses

    cfg = dataclasses.replace(base_config, reject_unknown_symbols=True)
    intent = make_intent(symbol="ZZZ", qty=1)
    ctx = _ctx(cfg, sectors, intent, _snap(), ref_price=D("100"), post_qty=D("1"))
    result = SectorExposureRule().evaluate(ctx)
    assert result.rejected
    assert "no sector" in (result.reason or "").lower()


# ── DailyLossRule ─────────────────────────────────────────────────────
def test_daily_loss_passes_when_within_limit(base_config, sectors):
    snap = _snap(cash=D("99000"), sod_equity=D("100000"))  # -1% drawdown
    intent = make_intent(symbol="MSFT", qty=1)
    ctx = _ctx(base_config, sectors, intent, snap, post_qty=D("1"))
    assert not DailyLossRule().evaluate(ctx).rejected


def test_daily_loss_rejects_risk_increasing_buy_when_breached(base_config, sectors):
    # -3% drawdown exceeds 2% limit
    snap = _snap(cash=D("97000"), sod_equity=D("100000"))
    intent = make_intent(symbol="MSFT", qty=1, side=Side.BUY)
    ctx = _ctx(base_config, sectors, intent, snap, post_qty=D("1"))
    result = DailyLossRule().evaluate(ctx)
    assert result.rejected
    assert "drawdown" in (result.reason or "")


def test_daily_loss_allows_closing_sell_when_breached(base_config, sectors):
    existing = {"AAPL": Position("AAPL", D("10"), D("100"))}
    snap = _snap(
        cash=D("90000"),
        positions=existing,
        marks={"AAPL": D("90")},
        sod_equity=D("100000"),
    )
    # equity = 90000 + 900 = 90900 → -9.1% drawdown
    intent = make_intent(symbol="AAPL", qty=4, side=Side.SELL)
    # post_qty: 10 - 4 = 6 (still long, reduced)
    ctx = _ctx(base_config, sectors, intent, snap, ref_price=D("90"), post_qty=D("6"))
    assert not DailyLossRule().evaluate(ctx).rejected


def test_daily_loss_rejects_opening_short_when_breached(base_config, sectors):
    snap = _snap(cash=D("97000"), sod_equity=D("100000"))  # -3%
    intent = make_intent(symbol="MSFT", qty=1, side=Side.SELL)
    ctx = _ctx(base_config, sectors, intent, snap, post_qty=D("-1"))
    result = DailyLossRule().evaluate(ctx)
    assert result.rejected
