from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from .config import get_settings


class InputField(BaseModel):
    name: str
    description: str
    required: bool = True
    format: Literal["url", "string", "integer"] = "string"
    default: str | int | None = None
    minimum: int | None = None
    maximum: int | None = None
    max_length: int | None = Field(default=2048, ge=1, le=16384)


class ProviderConfig(BaseModel):
    name: Literal["scrapecreators", "apify", "mock"]
    route: str = ""
    method: Literal["GET", "POST"] = "POST"
    actor_id: str = ""
    max_total_charge_microusd: int = Field(default=0, ge=0)


class ServiceDefinition(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
    title: str
    platform: str
    description: str
    input_fields: list[InputField]
    provider: ProviderConfig
    execution: Literal["sync", "async"] = "sync"
    response_shape: Literal["profile", "item", "feed", "stories"] = "profile"
    enabled: bool = False
    public: bool = False
    timeout_seconds: int = Field(default=25, ge=1, le=120)
    retries: int = Field(default=0, ge=0, le=2)
    cache_ttl_seconds: int | None = Field(default=None, ge=0, le=86400)
    estimated_upstream_cost_cents: int = Field(default=0, ge=0)
    estimated_upstream_cost_microusd: int = Field(default=0, ge=0)
    provider_unit_cost_microusd: int = Field(default=0, ge=0)
    cost_verified: bool = False
    price_cents: int = Field(default=5, ge=0)
    docs: str = ""
    catalog_status: Literal["available", "validation", "planned", "paused"] | None = None

    @model_validator(mode="after")
    def validate_release_safety(self) -> ServiceDefinition:
        if self.public and not self.enabled:
            raise ValueError("A public service must also be enabled")
        if self.catalog_status == "available" and not (self.enabled and self.public):
            raise ValueError("An available catalog service must be enabled and public")
        if self.enabled and self.public and self.catalog_status not in {None, "available"}:
            raise ValueError("An enabled public service must have available catalog status")
        if self.provider.name == "apify" and self.enabled:
            if not self.provider.actor_id:
                raise ValueError("An enabled Apify service requires an actor ID")
            if self.provider.max_total_charge_microusd <= 0:
                raise ValueError("An enabled Apify service requires a positive charge cap")
            if self.retries:
                raise ValueError("Apify services cannot automatically create replacement runs")
        if self.public:
            conservative_cost = max(
                self.estimated_upstream_cost_microusd,
                self.provider.max_total_charge_microusd,
            )
            price_microusd = self.price_cents * 10_000
            if conservative_cost and (
                price_microusd - conservative_cost < 10_000
                or price_microusd < conservative_cost * 2
            ):
                raise ValueError(
                    "A public service requires at least one cent and 50% gross margin"
                )
        return self

    @property
    def effective_cache_ttl(self) -> int:
        return (
            self.cache_ttl_seconds
            if self.cache_ttl_seconds is not None
            else get_settings().cache_ttl_seconds
        )

    @property
    def is_async(self) -> bool:
        return self.execution == "async"

    @property
    def status(self) -> Literal["available", "validation", "planned", "paused"]:
        if self.enabled and self.public:
            return "available"
        return self.catalog_status or "planned"


class Catalog(BaseModel):
    services: list[ServiceDefinition]

    def by_id(self, service_id: str) -> ServiceDefinition | None:
        return next((service for service in self.services if service.id == service_id), None)

    def public_services(self) -> list[ServiceDefinition]:
        return [service for service in self.services if service.enabled and service.public]

    def discoverable_services(self) -> list[ServiceDefinition]:
        """Return the product roadmap without implying that a route can execute."""
        return list(self.services)

    def platforms(self) -> list[str]:
        return sorted({service.platform for service in self.discoverable_services()})


def load_catalog(path: Path | None = None) -> Catalog:
    catalog_path = path or get_settings().catalog_path
    with catalog_path.open("r", encoding="utf-8") as handle:
        raw: dict[str, Any] = yaml.safe_load(handle) or {}
    catalog = Catalog.model_validate(raw)
    service_ids = [service.id for service in catalog.services]
    if len(service_ids) != len(set(service_ids)):
        raise ValueError("Service IDs must be unique")
    return catalog


@lru_cache
def get_catalog() -> Catalog:
    return load_catalog()


def clear_catalog_cache() -> None:
    get_catalog.cache_clear()
