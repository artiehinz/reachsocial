from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from .catalog import ServiceDefinition
from .config import get_settings
from .errors import ProviderTimeout, ProviderUnavailable


@dataclass(frozen=True)
class ProviderResult:
    data: dict[str, Any]
    upstream_cost_cents: int


class ProviderAdapter(Protocol):
    async def execute(
        self, service: ServiceDefinition, input_data: dict[str, Any]
    ) -> ProviderResult: ...


class ConfiguredHttpAdapter:
    provider_name: str

    def __init__(self, provider_name: str, token: str) -> None:
        self.provider_name = provider_name
        self.token = token

    async def execute(
        self, service: ServiceDefinition, input_data: dict[str, Any]
    ) -> ProviderResult:
        if not self.token or not service.provider.route:
            raise ProviderUnavailable(f"{self.provider_name} route is not configured")
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=service.timeout_seconds) as client:
                response = await client.request(
                    service.provider.method,
                    service.provider.route,
                    headers=headers,
                    json={"input": input_data},
                )
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"{self.provider_name} timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"{self.provider_name} request failed") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderUnavailable(f"{self.provider_name} returned invalid JSON") from exc
        return ProviderResult(
            data=payload, upstream_cost_cents=service.estimated_upstream_cost_cents
        )


class MockAdapter:
    async def execute(
        self, service: ServiceDefinition, input_data: dict[str, Any]
    ) -> ProviderResult:
        return ProviderResult(
            data={"provider_payload": {"service": service.id, "input": input_data}},
            upstream_cost_cents=service.estimated_upstream_cost_cents,
        )


def adapter_for(service: ServiceDefinition) -> ProviderAdapter:
    settings = get_settings()
    if service.provider.name == "mock":
        return MockAdapter()
    if service.provider.name == "scrapecreators":
        return ConfiguredHttpAdapter("scrapecreators", settings.scrapecreators_api_key)
    if service.provider.name == "apify":
        return ConfiguredHttpAdapter("apify", settings.apify_api_token)
    raise ProviderUnavailable("No provider adapter is configured")
