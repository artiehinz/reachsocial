from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from .config import get_settings


class InputField(BaseModel):
    name: str
    description: str
    required: bool = True
    format: Literal["url", "string", "integer"] = "string"


class ProviderConfig(BaseModel):
    name: Literal["scrapecreators", "apify", "mock"]
    route: str = ""
    method: Literal["GET", "POST"] = "POST"
    actor_id: str = ""


class ServiceDefinition(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
    title: str
    platform: str
    description: str
    input_fields: list[InputField]
    provider: ProviderConfig
    enabled: bool = False
    public: bool = False
    timeout_seconds: int = Field(default=25, ge=1, le=120)
    retries: int = Field(default=0, ge=0, le=2)
    cache_ttl_seconds: int | None = Field(default=None, ge=0, le=86400)
    estimated_upstream_cost_cents: int = Field(default=0, ge=0)
    price_cents: int = Field(default=5, ge=0)
    docs: str = ""

    @property
    def effective_cache_ttl(self) -> int:
        return (
            self.cache_ttl_seconds
            if self.cache_ttl_seconds is not None
            else get_settings().cache_ttl_seconds
        )


class Catalog(BaseModel):
    services: list[ServiceDefinition]

    def by_id(self, service_id: str) -> ServiceDefinition | None:
        return next((service for service in self.services if service.id == service_id), None)

    def public_services(self) -> list[ServiceDefinition]:
        return [service for service in self.services if service.enabled and service.public]


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
