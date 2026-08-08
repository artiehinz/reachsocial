from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    public_base_url: HttpUrl = "http://localhost:8000"
    database_url: str = "sqlite:///./data/reachsocial.db"
    catalog_path: Path = Path("config/services.yaml")
    scrapecreators_api_key: str = ""
    apify_api_token: str = ""
    mcp_enabled: bool = False
    admin_api_token: str = ""
    x402_enabled: bool = False
    x402_network: str = "eip155:84532"
    x402_pay_to: str = ""
    x402_facilitator_url: str = ""
    default_rate_limit_per_minute: int = Field(default=30, ge=1, le=10000)
    default_concurrency_limit: int = Field(default=2, ge=1, le=1000)
    default_daily_spend_cents: int = Field(default=5000, ge=0)
    provider_concurrency_limit: int = Field(default=4, ge=1, le=1000)
    max_daily_upstream_cost_cents: int = Field(default=10000, ge=0)
    cache_ttl_seconds: int = Field(default=60, ge=0, le=86400)
    request_retention_days: int = Field(default=30, ge=1, le=3650)

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
