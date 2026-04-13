from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from .types import Mode


@dataclass(frozen=True, slots=True)
class PositionCap:
    max_notional: Decimal
    max_pct_equity: Decimal


@dataclass(frozen=True, slots=True)
class ReconcilerConfig:
    interval_seconds: int = 60
    qty_tolerance: Decimal = Decimal("0")
    cash_tolerance_pct: Decimal = Decimal("0.001")
    max_consecutive_failures: int = 5


@dataclass(frozen=True, slots=True)
class BrokerConfig:
    kind: str = "simulated"
    base_url: str | None = None
    key_env: str | None = None
    secret_env: str | None = None


@dataclass(frozen=True, slots=True)
class RiskConfig:
    mode: Mode = Mode.BACKTEST
    workdir: Path = Path("./state")
    db_path: Path | None = None
    sectors_path: Path = Path("./data/sectors.json")
    kill_switch: bool = False
    reject_unknown_symbols: bool = False
    max_daily_loss_pct: Decimal = Decimal("0.02")
    default_position_cap: PositionCap = field(
        default_factory=lambda: PositionCap(Decimal("25000"), Decimal("0.05"))
    )
    symbol_position_caps: dict[str, PositionCap] = field(default_factory=dict)
    default_sector_cap_pct: Decimal = Decimal("0.25")
    sector_caps_pct: dict[str, Decimal] = field(default_factory=dict)
    reconciler: ReconcilerConfig = field(default_factory=ReconcilerConfig)
    broker: BrokerConfig = field(default_factory=BrokerConfig)

    def cap_for(self, symbol: str) -> PositionCap:
        return self.symbol_position_caps.get(symbol, self.default_position_cap)

    def sector_cap_pct_for(self, sector: str) -> Decimal:
        return self.sector_caps_pct.get(sector, self.default_sector_cap_pct)

    def resolved_db_path(self) -> Path:
        if self.db_path is not None:
            return self.db_path
        if self.mode is Mode.BACKTEST:
            return Path(":memory:")
        return self.workdir / f"{self.mode.value}.db"


def _to_decimal(x: Any) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def _parse_position_cap(d: dict[str, Any]) -> PositionCap:
    return PositionCap(
        max_notional=_to_decimal(d["max_notional"]),
        max_pct_equity=_to_decimal(d["max_pct_equity"]),
    )


def parse_config(raw: dict[str, Any]) -> RiskConfig:
    pos_caps_raw = raw.get("position_caps", {}) or {}
    default_cap_raw = pos_caps_raw.get("default")
    default_cap = (
        _parse_position_cap(default_cap_raw)
        if default_cap_raw is not None
        else RiskConfig.__dataclass_fields__["default_position_cap"].default_factory()  # type: ignore[misc]
    )
    symbol_caps = {
        sym: _parse_position_cap(cap)
        for sym, cap in pos_caps_raw.items()
        if sym != "default"
    }

    sec_caps_raw = raw.get("sector_caps", {}) or {}
    default_sector = _to_decimal(sec_caps_raw.get("default", "0.25"))
    sector_caps = {
        sec: _to_decimal(v) for sec, v in sec_caps_raw.items() if sec != "default"
    }

    reconciler_raw = raw.get("reconciler", {}) or {}
    reconciler = ReconcilerConfig(
        interval_seconds=int(reconciler_raw.get("interval_seconds", 60)),
        qty_tolerance=_to_decimal(reconciler_raw.get("qty_tolerance", "0")),
        cash_tolerance_pct=_to_decimal(reconciler_raw.get("cash_tolerance_pct", "0.001")),
        max_consecutive_failures=int(reconciler_raw.get("max_consecutive_failures", 5)),
    )

    broker_raw = raw.get("broker", {}) or {}
    broker = BrokerConfig(
        kind=broker_raw.get("kind", "simulated"),
        base_url=broker_raw.get("base_url"),
        key_env=broker_raw.get("key_env"),
        secret_env=broker_raw.get("secret_env"),
    )

    workdir = Path(raw.get("workdir", "./state"))
    db_path_raw = raw.get("db_path")

    return RiskConfig(
        mode=Mode(raw.get("mode", "backtest")),
        workdir=workdir,
        db_path=Path(db_path_raw) if db_path_raw else None,
        sectors_path=Path(raw.get("sectors_path", "./data/sectors.json")),
        kill_switch=bool(raw.get("kill_switch", False)),
        reject_unknown_symbols=bool(raw.get("reject_unknown_symbols", False)),
        max_daily_loss_pct=_to_decimal(raw.get("max_daily_loss_pct", "0.02")),
        default_position_cap=default_cap,
        symbol_position_caps=symbol_caps,
        default_sector_cap_pct=default_sector,
        sector_caps_pct=sector_caps,
        reconciler=reconciler,
        broker=broker,
    )


def load_config(path: str | Path) -> RiskConfig:
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    return parse_config(raw)
