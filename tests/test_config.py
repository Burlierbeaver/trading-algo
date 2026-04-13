from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from risk_manager.config import load_config, parse_config
from risk_manager.types import Mode


def test_parse_config_minimal():
    cfg = parse_config({"mode": "paper"})
    assert cfg.mode is Mode.PAPER
    assert cfg.max_daily_loss_pct == Decimal("0.02")
    assert cfg.default_position_cap.max_notional == Decimal("25000")


def test_parse_config_full(tmp_path):
    raw = {
        "mode": "live",
        "workdir": str(tmp_path),
        "kill_switch": True,
        "max_daily_loss_pct": "0.015",
        "position_caps": {
            "default": {"max_notional": "10000", "max_pct_equity": "0.03"},
            "AAPL": {"max_notional": "20000", "max_pct_equity": "0.08"},
        },
        "sector_caps": {
            "default": "0.20",
            "Technology": "0.30",
            "UNKNOWN": "0.02",
        },
        "reconciler": {
            "interval_seconds": 30,
            "qty_tolerance": "0.001",
            "cash_tolerance_pct": "0.0005",
        },
        "broker": {"kind": "alpaca", "key_env": "ALPACA_KEY"},
    }
    cfg = parse_config(raw)
    assert cfg.mode is Mode.LIVE
    assert cfg.kill_switch is True
    assert cfg.default_position_cap.max_notional == Decimal("10000")
    assert cfg.symbol_position_caps["AAPL"].max_pct_equity == Decimal("0.08")
    assert cfg.default_sector_cap_pct == Decimal("0.20")
    assert cfg.sector_caps_pct["Technology"] == Decimal("0.30")
    assert cfg.reconciler.interval_seconds == 30
    assert cfg.broker.kind == "alpaca"


def test_load_config_from_yaml_file(tmp_path):
    path = tmp_path / "cfg.yaml"
    path.write_text("mode: backtest\nmax_daily_loss_pct: 0.03\n")
    cfg = load_config(path)
    assert cfg.mode is Mode.BACKTEST
    assert cfg.max_daily_loss_pct == Decimal("0.03")


def test_resolved_db_path_backtest_uses_memory():
    cfg = parse_config({"mode": "backtest"})
    assert str(cfg.resolved_db_path()) == ":memory:"


def test_resolved_db_path_paper_uses_workdir(tmp_path):
    cfg = parse_config({"mode": "paper", "workdir": str(tmp_path)})
    assert cfg.resolved_db_path() == Path(tmp_path) / "paper.db"
