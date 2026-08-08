from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

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


class ScrapeCreatorsAdapter:
    """Adapter for the documented ScrapeCreators Instagram endpoints."""

    base_url = "https://api.scrapecreators.com"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    @staticmethod
    def _instagram_handle(value: object) -> str:
        parsed = urlparse(str(value))
        segments = [part for part in parsed.path.split("/") if part]
        if len(segments) != 1 or segments[0] in {"p", "reel", "tv", "explore"}:
            raise ProviderUnavailable("A canonical Instagram profile URL is required")
        return segments[0].removeprefix("@")

    @classmethod
    def request_for(cls, service: ServiceDefinition, input_data: dict[str, Any]) -> tuple[str, dict[str, str]]:
        url = str(input_data.get("url", ""))
        if service.id == "instagram.profile":
            return (
                f"{cls.base_url}/v1/instagram/profile",
                {"handle": cls._instagram_handle(url)},
            )
        if service.id == "instagram.post":
            return (
                f"{cls.base_url}/v1/instagram/post",
                # ReachSocial returns source media URLs; it never asks the provider
                # to download or store media on the customer's behalf.
                {"url": url, "download_media": "false"},
            )
        raise ProviderUnavailable(f"ScrapeCreators is not configured for {service.id}")

    async def execute(
        self, service: ServiceDefinition, input_data: dict[str, Any]
    ) -> ProviderResult:
        if not self.api_key:
            raise ProviderUnavailable("ScrapeCreators API key is not configured")
        url, params = self.request_for(service, input_data)
        headers = {"x-api-key": self.api_key, "Accept": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=service.timeout_seconds) as client:
                response = await client.get(url, headers=headers, params=params)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProviderTimeout("ScrapeCreators timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable("ScrapeCreators request failed") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderUnavailable("ScrapeCreators returned invalid JSON") from exc
        if not payload.get("success", False):
            raise ProviderUnavailable("ScrapeCreators did not return a successful result")
        return ProviderResult(
            data={
                "provider": "scrapecreators",
                "result": payload.get("data", {}),
                "provider_meta": {
                    "cached": bool(payload.get("cached", False)),
                    "credits_charged": payload.get("credits_charged", 0),
                },
            },
            upstream_cost_cents=service.estimated_upstream_cost_cents,
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
        return ScrapeCreatorsAdapter(settings.scrapecreators_api_key)
    if service.provider.name == "apify":
        return ConfiguredHttpAdapter("apify", settings.apify_api_token)
    raise ProviderUnavailable("No provider adapter is configured")
