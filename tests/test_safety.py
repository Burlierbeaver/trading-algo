from decimal import Decimal
from pathlib import Path

import pytest

from alpaca_broker_adapter.config import Settings, TradingMode
from alpaca_broker_adapter.errors import SafetyRailViolation
from alpaca_broker_adapter.models import OrderRequest, OrderSide, OrderType
from alpaca_broker_adapter.safety import preflight_check


def _order(**kw) -> OrderRequest:
    return OrderRequest(
        symbol=kw.pop("symbol", "AAPL"),
        side=kw.pop("side", OrderSide.BUY),
        qty=kw.pop("qty", Decimal("1")),
        **kw,
    )


def _live(**overrides) -> Settings:
    defaults = dict(
        alpaca_mode=TradingMode.LIVE,
        alpaca_api_key="k",
        alpaca_api_secret="s",
        database_url="postgresql://unused",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_paper_mode_bypasses_all_rails(tmp_path: Path):
    kill = tmp_path / "KILL"
    kill.write_text("x")
    s = Settings(
        alpaca_mode=TradingMode.PAPER,
        alpaca_api_key="k",
        alpaca_api_secret="s",
        database_url="postgresql://unused",
        max_qty_per_order=Decimal("1"),
        max_notional_per_order=Decimal("1"),
        symbol_whitelist="ZZZZ",
        kill_switch_file=kill,
    )
    preflight_check(_order(qty=Decimal("9999"), symbol="AAPL"), s)  # no-op


def test_kill_switch_blocks_when_file_exists(tmp_path: Path):
    kill = tmp_path / "KILL"
    kill.write_text("stop")
    s = _live(kill_switch_file=kill)
    with pytest.raises(SafetyRailViolation, match="kill switch"):
        preflight_check(_order(), s)


def test_kill_switch_inactive_when_missing(tmp_path: Path):
    s = _live(kill_switch_file=tmp_path / "not-there")
    preflight_check(_order(), s)  # no raise


def test_symbol_whitelist_allows_and_blocks():
    s = _live(symbol_whitelist="SPY, QQQ ,AAPL")
    preflight_check(_order(symbol="aapl"), s)  # case-insensitive
    with pytest.raises(SafetyRailViolation, match="not in whitelist"):
        preflight_check(_order(symbol="TSLA"), s)


def test_max_qty_per_order():
    s = _live(max_qty_per_order=Decimal("10"))
    preflight_check(_order(qty=Decimal("10")), s)
    with pytest.raises(SafetyRailViolation, match="max_qty_per_order"):
        preflight_check(_order(qty=Decimal("11")), s)


def test_max_notional_with_limit_price():
    s = _live(max_notional_per_order=Decimal("1000"))
    under = _order(qty=Decimal("9"), order_type=OrderType.LIMIT, limit_price=Decimal("100"))
    preflight_check(under, s)
    over = _order(qty=Decimal("11"), order_type=OrderType.LIMIT, limit_price=Decimal("100"))
    with pytest.raises(SafetyRailViolation, match="max_notional"):
        preflight_check(over, s)


def test_max_notional_with_reference_price():
    s = _live(max_notional_per_order=Decimal("500"))
    o = _order(qty=Decimal("10"))  # market order, no price on order
    preflight_check(o, s, reference_price=Decimal("49"))
    with pytest.raises(SafetyRailViolation, match="max_notional"):
        preflight_check(o, s, reference_price=Decimal("51"))


def test_max_notional_with_notional_order():
    s = _live(max_notional_per_order=Decimal("500"))
    o = OrderRequest(symbol="AAPL", side=OrderSide.BUY, notional=Decimal("400"))
    preflight_check(o, s)
    too_big = OrderRequest(symbol="AAPL", side=OrderSide.BUY, notional=Decimal("600"))
    with pytest.raises(SafetyRailViolation, match="max_notional"):
        preflight_check(too_big, s)


def test_max_notional_skipped_without_price_signal():
    # Market order + no reference price = no notional available -> do not raise.
    s = _live(max_notional_per_order=Decimal("1"))
    preflight_check(_order(qty=Decimal("9999")), s)  # allowed; no notional known
