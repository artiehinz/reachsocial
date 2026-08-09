from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from .catalog import ServiceDefinition
from .config import get_settings
from .errors import (
    InvalidInput,
    PrivateOrUnavailable,
    ProviderAccessDenied,
    ProviderRateLimit,
    ProviderTimeout,
    ProviderUnavailable,
    ResourceNotFound,
)
from .normalized import normalize_provider_payload


@dataclass(frozen=True)
class ProviderResult:
    data: dict[str, Any]
    upstream_cost_microusd: int
    provider_units: int = 0
    provider_unit_cost_microusd: int = 0
    provider_reference: str | None = None


class ProviderAdapter(Protocol):
    async def execute(
        self, service: ServiceDefinition, input_data: dict[str, Any]
    ) -> ProviderResult: ...


def _segments(url: object) -> list[str]:
    return [part for part in urlparse(str(url or "")).path.split("/") if part]


def _handle(url: object) -> str:
    parts = _segments(url)
    if not parts:
        raise ProviderUnavailable("The canonical profile URL has no handle")
    if parts[0] in {"in", "pub"} and len(parts) > 1:
        return parts[1]
    return parts[0].removeprefix("@")


def _http_error(provider: str, response: httpx.Response) -> Exception:
    if response.status_code in {400, 422}:
        return InvalidInput("The provider rejected the normalized input")
    if response.status_code in {404, 410}:
        return ResourceNotFound("The public social resource was not found")
    if provider == "Apify" and response.status_code in {401, 402, 403}:
        return ProviderAccessDenied("Apify authentication, billing, or actor access failed")
    if provider == "ScrapeCreators" and response.status_code in {401, 402}:
        return ProviderAccessDenied("ScrapeCreators authentication or credit access failed")
    if response.status_code == 403:
        return PrivateOrUnavailable("The public social resource is private or unavailable")
    if response.status_code == 429:
        return ProviderRateLimit(f"{provider} is temporarily rate limited")
    return ProviderUnavailable(f"{provider} request failed")


def _costed_error(
    error: Exception,
    *,
    reference: str | None = None,
    units: int = 0,
    unit_cost_microusd: int = 0,
    upstream_cost_microusd: int = 0,
) -> Exception:
    error.provider_reference = reference  # type: ignore[attr-defined]
    error.provider_units = units  # type: ignore[attr-defined]
    error.provider_unit_cost_microusd = unit_cost_microusd  # type: ignore[attr-defined]
    error.upstream_cost_microusd = upstream_cost_microusd  # type: ignore[attr-defined]
    return error


class ScrapeCreatorsAdapter:
    base_url = "https://api.scrapecreators.com"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    @classmethod
    def request_for(
        cls, service: ServiceDefinition, input_data: dict[str, Any]
    ) -> tuple[str, dict[str, str]]:
        canonical_url = str(input_data.get("url", ""))
        routes: dict[str, tuple[str, dict[str, str]]] = {
            "instagram.profile": ("/v1/instagram/profile", {"handle": _handle(canonical_url)}),
            "instagram.post": (
                "/v1/instagram/post",
                {"url": canonical_url, "download_media": "false"},
            ),
            "x.profile": ("/v1/twitter/profile", {"handle": _handle(canonical_url)}),
            "x.post": ("/v1/twitter/tweet", {"url": canonical_url}),
            "tiktok.profile": ("/v1/tiktok/profile", {"handle": _handle(canonical_url)}),
            "tiktok.feed": (
                "/v3/tiktok/profile/videos",
                {
                    "handle": _handle(canonical_url),
                    "max_cursor": str(input_data.get("cursor") or "0"),
                    "sort_by": "latest",
                },
            ),
            "tiktok.video": ("/v2/tiktok/video", {"url": canonical_url}),
        }
        route = routes.get(service.id)
        if route is None:
            raise ProviderUnavailable(f"ScrapeCreators is not configured for {service.id}")
        return f"{cls.base_url}{route[0]}", route[1]

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
        except httpx.TimeoutException as exc:
            raise ProviderTimeout("ScrapeCreators timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable("ScrapeCreators connection failed") from exc
        if response.status_code >= 400:
            raise _http_error("ScrapeCreators", response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderUnavailable("ScrapeCreators returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ProviderUnavailable("ScrapeCreators returned an unexpected response")
        credits_value = payload.get("credits_charged")
        credits = max(
            0,
            int(
                credits_value
                if credits_value is not None
                else (0 if payload.get("cached") is True else 1)
            ),
        )
        unit_cost = service.provider_unit_cost_microusd
        if payload.get("success") is False:
            raise _costed_error(
                ProviderUnavailable("ScrapeCreators did not return a successful result"),
                reference=response.headers.get("x-request-id"),
                units=credits,
                unit_cost_microusd=unit_cost,
                upstream_cost_microusd=credits * unit_cost,
            )
        normalized = normalize_provider_payload(service.id, str(input_data["url"]), payload)
        if service.response_shape in {"feed", "stories"}:
            limit = int(input_data.get("max_items") or 20)
            normalized["items"] = normalized.get("items", [])[:limit]
        return ProviderResult(
            data=normalized,
            upstream_cost_microusd=credits * unit_cost,
            provider_units=credits,
            provider_unit_cost_microusd=unit_cost,
            provider_reference=response.headers.get("x-request-id"),
        )


class ApifyAdapter:
    base_url = "https://api.apify.com/v2"

    def __init__(self, token: str) -> None:
        self.token = token

    @staticmethod
    def payload_for(service: ServiceDefinition, input_data: dict[str, Any]) -> dict[str, Any]:
        canonical_url = str(input_data.get("url", ""))
        if service.id == "instagram.stories":
            return {"profiles": [canonical_url]}
        if service.id == "x.feed":
            return {
                "includeSearchTerms": False,
                "maxItems": int(input_data.get("max_items") or 20),
                "onlyImage": False,
                "onlyQuote": False,
                "onlyTwitterBlue": False,
                "onlyVerifiedUsers": False,
                "onlyVideo": False,
                "searchTerms": [f"from:{_handle(canonical_url)}"],
                "sort": "Latest",
            }
        if service.id == "linkedin.profile":
            return {"profileUrls": [canonical_url], "maxProfiles": 1}
        raise ProviderUnavailable(f"Apify is not configured for {service.id}")

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        try:
            response = await client.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout("Apify timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable("Apify connection failed") from exc
        if response.status_code >= 400:
            raise _http_error("Apify", response)
        return response

    async def execute(
        self, service: ServiceDefinition, input_data: dict[str, Any]
    ) -> ProviderResult:
        if not self.token or not service.provider.actor_id:
            raise ProviderUnavailable("Apify actor or token is not configured")
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        deadline = time.monotonic() + service.timeout_seconds
        timeout = min(30, service.timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await self._request(
                client,
                "POST",
                f"{self.base_url}/acts/{service.provider.actor_id}/runs",
                headers=headers,
                json=self.payload_for(service, input_data),
            )
            try:
                run = (response.json() or {}).get("data") or response.json()
            except ValueError as exc:
                raise ProviderUnavailable("Apify returned invalid run JSON") from exc
            run_id = str(run.get("id") or run.get("runId") or "")
            dataset_id = run.get("defaultDatasetId")
            status = str(run.get("status") or "").upper()
            if not run_id:
                raise ProviderUnavailable("Apify did not return a run ID")
            while status not in {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}:
                if time.monotonic() >= deadline:
                    raise ProviderTimeout("Apify job did not finish before its deadline")
                await asyncio.sleep(2)
                check = await self._request(
                    client,
                    "GET",
                    f"{self.base_url}/actor-runs/{run_id}",
                    headers=headers,
                )
                try:
                    run = (check.json() or {}).get("data") or check.json()
                except ValueError as exc:
                    raise ProviderUnavailable("Apify returned invalid status JSON") from exc
                status = str(run.get("status") or "").upper()
                dataset_id = run.get("defaultDatasetId") or dataset_id
            try:
                run_cost = round(float(run.get("usageTotalUsd") or 0) * 1_000_000)
            except (TypeError, ValueError):
                run_cost = 0
            if status != "SUCCEEDED":
                raise _costed_error(
                    ProviderUnavailable(f"Apify job ended with status {status.lower()}"),
                    reference=run_id,
                    upstream_cost_microusd=run_cost,
                )
            if not dataset_id:
                raise ProviderUnavailable("Apify job completed without a dataset")
            max_items = int(input_data.get("max_items") or (50 if service.id == "instagram.stories" else 20))
            dataset = await self._request(
                client,
                "GET",
                f"{self.base_url}/datasets/{dataset_id}/items",
                headers=headers,
                params={"clean": "1", "limit": str(max_items)},
            )
            try:
                items = dataset.json()
            except ValueError as exc:
                raise ProviderUnavailable("Apify returned invalid dataset JSON") from exc
            if not isinstance(items, list):
                raise ProviderUnavailable("Apify returned an unexpected dataset")
            actual_cost = run_cost
            units = len(items)
            unit_cost = (
                round(actual_cost / units)
                if actual_cost and units
                else service.provider_unit_cost_microusd
            )
            if not actual_cost:
                actual_cost = max(service.estimated_upstream_cost_microusd, units * unit_cost)
            return ProviderResult(
                data=normalize_provider_payload(
                    service.id, str(input_data["url"]), {"items": items}
                ),
                upstream_cost_microusd=actual_cost,
                provider_units=units,
                provider_unit_cost_microusd=unit_cost,
                provider_reference=run_id,
            )


class MockAdapter:
    async def execute(
        self, service: ServiceDefinition, input_data: dict[str, Any]
    ) -> ProviderResult:
        if service.response_shape == "profile":
            data = {
                "profile": {
                    "platform": service.platform,
                    "canonical_url": input_data.get("url"),
                    "platform_id": "mock-id",
                    "handle": _handle(input_data.get("url")),
                    "display_name": "Mock Profile",
                    "biography": None,
                    "avatar_url": None,
                    "verified": None,
                    "private": None,
                    "counts": {"followers": None, "following": None, "content": None},
                    "links": [],
                    "fields": {},
                }
            }
        elif service.response_shape in {"feed", "stories"}:
            data = {"profile": None, "items": [], "next_cursor": None, "has_more": False}
        else:
            data = {"item": {"platform": service.platform, "canonical_url": input_data.get("url")}}
        return ProviderResult(
            data=data,
            upstream_cost_microusd=service.estimated_upstream_cost_microusd,
            provider_unit_cost_microusd=service.provider_unit_cost_microusd,
        )


def adapter_for(service: ServiceDefinition) -> ProviderAdapter:
    settings = get_settings()
    if service.provider.name == "mock":
        return MockAdapter()
    if service.provider.name == "scrapecreators":
        return ScrapeCreatorsAdapter(settings.scrapecreators_api_key)
    if service.provider.name == "apify":
        return ApifyAdapter(settings.apify_api_token)
    raise ProviderUnavailable("No provider adapter is configured")
