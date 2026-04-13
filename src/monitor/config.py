from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://trader:trader@localhost:5432/trading"
    redis_url: str = "redis://localhost:6379/0"

    slack_webhook_url: str | None = None

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_to: str | None = None
    smtp_use_tls: bool = True

    heartbeat_stale_seconds: int = 15
    heartbeat_poll_seconds: int = 5
    heartbeat_repeat_suppress_seconds: int = 60

    sse_tick_seconds: float = Field(default=1.0, ge=0.1)

    app_host: str = "0.0.0.0"
    app_port: int = 8787
    log_level: str = "INFO"

    @property
    def slack_enabled(self) -> bool:
        return bool(self.slack_webhook_url)

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_from and self.smtp_to)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
