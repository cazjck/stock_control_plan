"""Cấu hình ứng dụng, đọc từ biến môi trường hoặc backend/.env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    data_dir: Path = Path("data")
    brokers: str = "demo"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    timezone: str = "Asia/Ho_Chi_Minh"
    app_access_token: str | None = Field(default=None)

    tcbs_api_key: str | None = None
    tcbs_custody_code: str | None = None
    tcbs_base_url: str = "https://openapi.tcbs.com.vn"

    dnse_api_key: str | None = None
    dnse_api_secret: str | None = None
    dnse_base_url: str = "https://openapi.dnse.com.vn"
    dnse_api_version: str = "2026-07-23"

    quote_ttl_seconds: int = 15
    candle_ttl_seconds: int = 1800
    account_ttl_seconds: int = 30

    @property
    def enabled_brokers(self) -> list[str]:
        return [b.strip().lower() for b in self.brokers.split(",") if b.strip()]

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def resolved_data_dir(self) -> Path:
        p = self.data_dir if self.data_dir.is_absolute() else BACKEND_DIR / self.data_dir
        p.mkdir(parents=True, exist_ok=True)
        return p


@lru_cache
def get_settings() -> Settings:
    return Settings()
