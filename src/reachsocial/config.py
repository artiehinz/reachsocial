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
    cdp_api_key_id: str = ""
    cdp_api_key_secret: str = ""
    support_email: str = "hello@artiehinz.com"
    external_backup_enabled: bool = False
    allow_mainnet_x402: bool = False
    mainnet_x402_canary_enabled: bool = False
    mainnet_x402_canary_buyer: str = ""
    minimum_public_margin_cents: int = Field(default=1, ge=1)
    maintenance_interval_hours: int = Field(default=24, ge=1, le=168)
    default_rate_limit_per_minute: int = Field(default=30, ge=1, le=10000)
    default_concurrency_limit: int = Field(default=2, ge=1, le=1000)
    default_daily_spend_cents: int = Field(default=5000, ge=0)
    provider_concurrency_limit: int = Field(default=4, ge=1, le=1000)
    max_daily_upstream_cost_microusd: int = Field(default=5_000_000, ge=0)
    public_test_rate_limit_per_minute: int = Field(default=5, ge=1, le=1000)
    public_test_daily_requests_per_identity: int = Field(default=20, ge=1, le=10000)
    cache_ttl_seconds: int = Field(default=60, ge=0, le=86400)
    request_retention_days: int = Field(default=30, ge=1, le=3650)
    async_job_retention_hours: int = Field(default=24, ge=1, le=168)
    async_job_lease_seconds: int = Field(default=180, ge=30, le=1800)
    async_worker_poll_seconds: float = Field(default=1.0, ge=0.1, le=30)
    service_credit_expiry_days: int = Field(default=30, ge=1, le=365)

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
