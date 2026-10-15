from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

MCP_SERVER_VERSION = "0.3.0"
_SERVICE_ID = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")


def configured_service_ids(value: str) -> frozenset[str]:
    """Parse an explicit, comma-separated operational service allowlist.

    Invalid values are returned as-is so the relevant fail-closed startup gate
    can report a useful configuration error instead of silently widening it.
    """
    return frozenset(item.strip() for item in value.split(",") if item.strip())


def valid_service_ids(value: frozenset[str]) -> bool:
    return bool(value) and all(_SERVICE_ID.fullmatch(item) for item in value)


def x402_network_label(network: str) -> str:
    """Return the human-facing name for a supported x402 network."""
    return {
        "eip155:8453": "Base mainnet",
        "eip155:84532": "Base Sepolia",
    }.get(network, network)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    public_base_url: HttpUrl = "http://localhost:8000"
    database_url: str = "sqlite:///./data/reachsocial.db"
    catalog_path: Path = Path("config/services.yaml")
    scrapecreators_api_key: str = ""
    mcp_enabled: bool = False
    oauth_enabled: bool = False
    mcp_payment_approval_enabled: bool = False
    # Optional temporary owner-only validation gate; empty permits self-service.
    oauth_validation_wallets: str = ""
    admin_api_token: str = ""
    x402_enabled: bool = False
    x402_network: str = "eip155:84532"
    x402_pay_to: str = ""
    x402_facilitator_url: str = ""
    cdp_api_key_id: str = ""
    cdp_api_key_secret: str = ""
    support_email: str = "hello@artiehinz.com"
    public_contact_email: str = "artemhinz2@gmail.com"
    external_backup_enabled: bool = False
    allow_mainnet_x402: bool = False
    mainnet_x402_canary_enabled: bool = False
    mainnet_x402_canary_buyer: str = ""
    mainnet_x402_acceptance_enabled: bool = False
    mainnet_x402_acceptance_buyer: str = ""
    # A short-lived, owner-only lane for validating one or more private
    # synchronous services through the real Base-mainnet payment pipeline.
    # It is not part of public discovery or ordinary REST execution.
    mainnet_private_acceptance_enabled: bool = False
    mainnet_private_acceptance_buyer: str = ""
    mainnet_private_acceptance_services: str = ""
    mainnet_private_acceptance_run_id: str = ""
    minimum_public_margin_cents: int = Field(default=1, ge=1)
    maintenance_interval_hours: int = Field(default=24, ge=1, le=168)
    default_rate_limit_per_minute: int = Field(default=30, ge=1, le=10000)
    default_concurrency_limit: int = Field(default=2, ge=1, le=1000)
    default_daily_spend_cents: int = Field(default=5000, ge=0)
    provider_concurrency_limit: int = Field(default=4, ge=1, le=1000)
    max_daily_upstream_cost_microusd: int = Field(default=5_000_000, ge=0)
    # A checked provider balance and a protected internal reserve are both required
    # before Base-mainnet public sales can consume ScrapeCreators credits.
    scrapecreators_credit_balance: int = Field(default=0, ge=0)
    scrapecreators_credit_reserve: int = Field(default=0, ge=0)
    public_payments_paused: bool = False
    public_test_rate_limit_per_minute: int = Field(default=5, ge=1, le=1000)
    public_provider_max_attempts: int = Field(default=3, ge=1, le=3)
    public_test_daily_requests_per_identity: int = Field(default=20, ge=1, le=10000)
    max_request_body_bytes: int = Field(default=65_536, ge=1_024, le=1_048_576)
    max_payment_header_bytes: int = Field(default=16_384, ge=1_024, le=65_536)
    runtime_cache_max_entries: int = Field(default=512, ge=1, le=100_000)
    runtime_cache_max_bytes: int = Field(default=33_554_432, ge=1_024, le=1_073_741_824)
    runtime_state_idle_seconds: int = Field(default=900, ge=60, le=86_400)
    cache_ttl_seconds: int = Field(default=60, ge=0, le=86400)
    request_retention_days: int = Field(default=30, ge=1, le=3650)
    async_job_retention_hours: int = Field(default=24, ge=1, le=168)
    paid_result_retention_hours: int = Field(default=720, ge=24, le=720)
    async_job_lease_seconds: int = Field(default=180, ge=30, le=1800)
    async_worker_poll_seconds: float = Field(default=1.0, ge=0.1, le=30)
    service_credit_expiry_days: int = Field(default=30, ge=1, le=365)
    backup_status_path: Path = Path("/data/backup-status.json")
    backup_max_age_hours: int = Field(default=30, ge=1, le=168)

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
