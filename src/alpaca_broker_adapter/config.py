from __future__ import annotations

from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    alpaca_mode: TradingMode = TradingMode.PAPER
    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""

    database_url: str = "postgresql://localhost:5432/trading_algo"

    poll_interval_s: float = 1.0
    poll_timeout_s: float = 30.0

    max_notional_per_order: Optional[Decimal] = None
    max_qty_per_order: Optional[Decimal] = None
    symbol_whitelist: Optional[str] = Field(default=None)
    kill_switch_file: Optional[Path] = None

    @property
    def whitelist_set(self) -> Optional[set[str]]:
        if not self.symbol_whitelist:
            return None
        return {s.strip().upper() for s in self.symbol_whitelist.split(",") if s.strip()}

    @property
    def is_live(self) -> bool:
        return self.alpaca_mode is TradingMode.LIVE

    @property
    def alpaca_base_url(self) -> str:
        return (
            "https://api.alpaca.markets"
            if self.is_live
            else "https://paper-api.alpaca.markets"
        )

    @field_validator("poll_interval_s", "poll_timeout_s")
    @classmethod
    def _positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("must be positive")
        return v
