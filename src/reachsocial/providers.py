from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
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
from .normalized import normalize_provider_payload, normalized_result_is_complete


@dataclass(frozen=True)
class ProviderResult:
    data: dict[str, Any]
    upstream_cost_microusd: int
    provider_units: int = 0
    provider_unit_cost_microusd: int = 0
    provider_reference: str | None = None


@dataclass(frozen=True)
class ProviderExecutionContext:
    existing_reference: str | None = None
    persist_reference: Callable[[str], None] | None = None


class ProviderAdapter(Protocol):
    async def execute(
        self,
        service: ServiceDefinition,
        input_data: dict[str, Any],
        *,
        context: ProviderExecutionContext | None = None,
    ) -> ProviderResult: ...


_GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
_GDELT_COUNTRY_CODES = {
    "argentina": "AR",
    "australia": "AU",
    "austria": "AT",
    "bangladesh": "BD",
    "belgium": "BE",
    "brazil": "BR",
    "canada": "CA",
    "chile": "CL",
    "china": "CN",
    "colombia": "CO",
    "czech republic": "CZ",
    "czechia": "CZ",
    "denmark": "DK",
    "egypt": "EG",
    "finland": "FI",
    "france": "FR",
    "germany": "DE",
    "greece": "GR",
    "hong kong": "HK",
    "hungary": "HU",
    "india": "IN",
    "indonesia": "ID",
    "ireland": "IE",
    "israel": "IL",
    "italy": "IT",
    "japan": "JP",
    "kenya": "KE",
    "malaysia": "MY",
    "mexico": "MX",
    "netherlands": "NL",
    "new zealand": "NZ",
    "nigeria": "NG",
    "norway": "NO",
    "pakistan": "PK",
    "peru": "PE",
    "philippines": "PH",
    "poland": "PL",
    "portugal": "PT",
    "romania": "RO",
    "russia": "RU",
    "saudi arabia": "SA",
    "singapore": "SG",
    "south africa": "ZA",
    "south korea": "KR",
    "spain": "ES",
    "sweden": "SE",
    "switzerland": "CH",
    "taiwan": "TW",
    "thailand": "TH",
    "turkey": "TR",
    "ukraine": "UA",
    "united arab emirates": "AE",
    "united kingdom": "GB",
    "united states": "US",
    "united states of america": "US",
    "vietnam": "VN",
}


def _clean_text(value: object, *, max_length: int) -> str | None:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return None
    return text[:max_length]


def _safe_public_url(value: object) -> str | None:
    text = _clean_text(value, max_length=4096)
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    return text


def _linkedin_provider_url(canonical_url: str) -> str:
    """Restore the public LinkedIn URL form required by ScrapeCreators.

    ReachSocial canonicalizes LinkedIn country aliases to one neutral host,
    while the provider documents and accepts the browser-facing www URL.
    """
    path = urlparse(canonical_url).path.rstrip("/")
    return f"https://www.linkedin.com{path}/"


def _gdelt_country_code(value: object) -> str | None:
    text = _clean_text(value, max_length=96)
    if not text:
        return None
    if len(text) == 2 and text.isalpha():
        return text.upper()
    return _GDELT_COUNTRY_CODES.get(text.casefold())


class GdeltAdapter:
    """Bounded GDELT DOC adapter for ReachSocial's private person-news contract."""

    base_url = _GDELT_DOC_URL
    # The B2B caller has a 60-second deadline. Keep the complete upstream
    # retry budget comfortably inside that contract.
    max_attempts = 2
    max_retry_sleep_seconds = 5.0

    @staticmethod
    def _query_name(value: object) -> str:
        full_name = _clean_text(value, max_length=200) or ""
        full_name = re.sub(r'["\\\x00-\x1f\x7f]', " ", full_name)
        full_name = " ".join(full_name.split())
        if len(full_name) < 2:
            raise InvalidInput("full_name must identify a public person")
        return full_name

    @classmethod
    def request_params(cls, input_data: dict[str, Any]) -> dict[str, str | int]:
        full_name = cls._query_name(input_data.get("full_name"))
        return {
            "query": f'"{full_name}"',
            "mode": "ArtList",
            "format": "JSON",
            "maxrecords": min(100, max(1, int(input_data.get("max_items") or 50))),
            "sort": "DateDesc",
        }

    @staticmethod
    def _normalized_data(payload: dict[str, Any], *, max_items: int) -> dict[str, Any]:
        rows = payload.get("articles")
        if not isinstance(rows, list):
            rows = []
        articles: list[dict[str, Any]] = []
        country_counts: dict[tuple[str, str], int] = {}
        seen_urls: set[str] = set()
        for row in rows[:max_items]:
            if not isinstance(row, dict):
                continue
            url = _safe_public_url(row.get("url"))
            title = _clean_text(row.get("title"), max_length=500)
            if not url or not title or url in seen_urls:
                continue
            seen_urls.add(url)
            country = _clean_text(row.get("sourcecountry"), max_length=96)
            country_code = _gdelt_country_code(country)
            image = _safe_public_url(row.get("socialimage"))
            domain = _clean_text(row.get("domain"), max_length=255)
            language = _clean_text(row.get("language"), max_length=64)
            published_at = _clean_text(row.get("seendate") or row.get("date"), max_length=64)
            article = {
                "title": title,
                "url": url,
                "image": image,
                "domain": domain,
                "published_at": published_at,
                "language": language,
                "country": country,
                "country_code": country_code,
            }
            articles.append({key: value for key, value in article.items() if value is not None})
            if country_code:
                key = (country_code, country or country_code)
                country_counts[key] = country_counts.get(key, 0) + 1
        countries = [
            {"code": code, "name": name, "count": count}
            for (code, name), count in sorted(
                country_counts.items(), key=lambda item: (-item[1], item[0][1])
            )
        ]
        return {"articles": articles, "countries": countries}

    async def execute(
        self,
        service: ServiceDefinition,
        input_data: dict[str, Any],
        *,
        context: ProviderExecutionContext | None = None,
    ) -> ProviderResult:
        del context
        params = self.request_params(input_data)
        response: httpx.Response | None = None
        async with httpx.AsyncClient(
            timeout=service.timeout_seconds,
            follow_redirects=False,
            headers={"Accept": "application/json", "User-Agent": "ReachSocial/1.0"},
        ) as client:
            for attempt in range(1, self.max_attempts + 1):
                try:
                    response = await client.get(self.base_url, params=params)
                except httpx.TimeoutException as exc:
                    if attempt >= self.max_attempts:
                        raise ProviderTimeout("GDELT timed out") from exc
                    await asyncio.sleep(min(self.max_retry_sleep_seconds, 2**attempt))
                    continue
                except httpx.HTTPError as exc:
                    raise ProviderUnavailable("GDELT connection failed") from exc
                if response.status_code == 429 and attempt < self.max_attempts:
                    raw_retry = response.headers.get("Retry-After", "")
                    try:
                        retry_after = float(raw_retry)
                    except ValueError:
                        retry_after = float(2**attempt)
                    await asyncio.sleep(min(self.max_retry_sleep_seconds, max(1.0, retry_after)))
                    continue
                break
        if response is None:
            raise ProviderUnavailable("GDELT did not return a response")
        if response.status_code == 429:
            raise ProviderRateLimit("GDELT is temporarily rate limited")
        if response.status_code >= 500:
            raise ProviderUnavailable("GDELT is temporarily unavailable")
        if response.status_code >= 400:
            raise InvalidInput("GDELT rejected the person-news query")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderUnavailable("GDELT returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ProviderUnavailable("GDELT returned an unexpected response")
        data = self._normalized_data(payload, max_items=int(params["maxrecords"]))
        return ProviderResult(
            data=data,
            upstream_cost_microusd=0,
            provider_units=1,
            provider_unit_cost_microusd=0,
            provider_reference=response.headers.get("x-request-id"),
        )


def _segments(url: object) -> list[str]:
    return [part for part in urlparse(str(url or "")).path.split("/") if part]


def _handle(url: object) -> str:
    parts = _segments(url)
    if not parts:
        raise ProviderUnavailable("The canonical profile URL has no handle")
    if parts[0] in {"in", "pub"} and len(parts) > 1:
        return parts[1]
    if parts[0] in {"c", "channel", "user"} and len(parts) > 1:
        return parts[1]
    return parts[0].removeprefix("@")


def _http_error(provider: str, response: httpx.Response) -> Exception:
    if response.status_code in {400, 422}:
        return InvalidInput("The provider rejected the normalized input")
    if response.status_code in {404, 410}:
        return ResourceNotFound("The public social resource was not found")
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
            "instagram.feed": (
                "/v2/instagram/user/posts",
                {"handle": _handle(canonical_url)},
            ),
            "instagram.post": (
                "/v1/instagram/post",
                {"url": canonical_url, "download_media": "false"},
            ),
            "instagram.highlight": (
                "/v1/instagram/user/highlight/detail",
                {"id": _segments(canonical_url)[-1]},
            ),
            "x.profile": ("/v1/twitter/profile", {"handle": _handle(canonical_url)}),
            "x.post": ("/v1/twitter/tweet", {"url": canonical_url}),
            "x.feed": (
                "/v1/twitter/user-tweets",
                {"handle": _handle(canonical_url)},
            ),
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
            "linkedin.profile": (
                "/v1/linkedin/profile",
                {"url": _linkedin_provider_url(canonical_url)},
            ),
            "youtube.channel": (
                "/v1/youtube/channel",
                {
                    "channelId" if _segments(canonical_url)[0] == "channel" else "handle": _handle(
                        canonical_url
                    )
                },
            ),
            "youtube.feed": (
                "/v1/youtube/channel-videos",
                {
                    "channelId" if _segments(canonical_url)[0] == "channel" else "handle": _handle(
                        canonical_url
                    ),
                    "sort": "latest",
                    "includeExtras": "true",
                },
            ),
            "youtube.video": ("/v1/youtube/video", {"url": canonical_url}),
            "facebook.profile": ("/v1/facebook/profile", {"url": canonical_url}),
            "reddit.post": ("/v1/reddit/post", {"url": canonical_url}),
        }
        route = routes.get(service.id)
        if route is None:
            raise ProviderUnavailable(f"ScrapeCreators is not configured for {service.id}")
        return f"{cls.base_url}{route[0]}", route[1]

    async def execute(
        self,
        service: ServiceDefinition,
        input_data: dict[str, Any],
        *,
        context: ProviderExecutionContext | None = None,
    ) -> ProviderResult:
        del context
        if not self.api_key:
            raise ProviderUnavailable("ScrapeCreators API key is not configured")
        url, params = self.request_for(service, input_data)
        headers = {"x-api-key": self.api_key, "Accept": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=service.timeout_seconds) as client:
                response = await client.get(url, headers=headers, params=params)
        except httpx.TimeoutException as exc:
            raise _costed_error(
                ProviderTimeout("ScrapeCreators timed out"),
                units=service.max_provider_units_per_attempt,
                unit_cost_microusd=service.provider_unit_cost_microusd,
                upstream_cost_microusd=(
                    service.max_provider_units_per_attempt * service.provider_unit_cost_microusd
                ),
            ) from exc
        except httpx.HTTPError as exc:
            raise _costed_error(
                ProviderUnavailable("ScrapeCreators connection failed"),
                units=service.max_provider_units_per_attempt,
                unit_cost_microusd=service.provider_unit_cost_microusd,
                upstream_cost_microusd=(
                    service.max_provider_units_per_attempt * service.provider_unit_cost_microusd
                ),
            ) from exc
        if response.status_code >= 400:
            raise _costed_error(
                _http_error("ScrapeCreators", response),
                reference=response.headers.get("x-request-id"),
                units=service.max_provider_units_per_attempt,
                unit_cost_microusd=service.provider_unit_cost_microusd,
                upstream_cost_microusd=(
                    service.max_provider_units_per_attempt * service.provider_unit_cost_microusd
                ),
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise _costed_error(
                ProviderUnavailable("ScrapeCreators returned invalid JSON"),
                reference=response.headers.get("x-request-id"),
                units=service.max_provider_units_per_attempt,
                unit_cost_microusd=service.provider_unit_cost_microusd,
                upstream_cost_microusd=(
                    service.max_provider_units_per_attempt * service.provider_unit_cost_microusd
                ),
            ) from exc
        if not isinstance(payload, dict):
            raise _costed_error(
                ProviderUnavailable("ScrapeCreators returned an unexpected response"),
                reference=response.headers.get("x-request-id"),
                units=service.max_provider_units_per_attempt,
                unit_cost_microusd=service.provider_unit_cost_microusd,
                upstream_cost_microusd=(
                    service.max_provider_units_per_attempt * service.provider_unit_cost_microusd
                ),
            )
        credits_value = payload.get("credits_charged")
        unit_cost = service.provider_unit_cost_microusd
        if credits_value is None:
            credits = 0 if payload.get("cached") is True else service.max_provider_units_per_attempt
        else:
            try:
                credits = int(credits_value)
            except (TypeError, ValueError) as exc:
                raise _costed_error(
                    ProviderUnavailable("ScrapeCreators returned invalid credit accounting"),
                    reference=response.headers.get("x-request-id"),
                    units=service.max_provider_units_per_attempt,
                    unit_cost_microusd=unit_cost,
                    upstream_cost_microusd=service.max_provider_units_per_attempt * unit_cost,
                ) from exc
            if credits < 0 or credits > service.max_provider_units_per_attempt:
                raise _costed_error(
                    ProviderUnavailable("ScrapeCreators credit use exceeded the verified limit"),
                    reference=response.headers.get("x-request-id"),
                    units=max(credits, service.max_provider_units_per_attempt),
                    unit_cost_microusd=unit_cost,
                    upstream_cost_microusd=max(credits, service.max_provider_units_per_attempt)
                    * unit_cost,
                )
        if payload.get("success") is False:
            raise _costed_error(
                ProviderUnavailable("ScrapeCreators did not return a successful result"),
                reference=response.headers.get("x-request-id"),
                units=credits,
                unit_cost_microusd=unit_cost,
                upstream_cost_microusd=credits * unit_cost,
            )
        normalized = normalize_provider_payload(service.id, str(input_data["url"]), payload)
        if not normalized_result_is_complete(service.id, normalized):
            raise _costed_error(
                ProviderUnavailable("ScrapeCreators returned an incomplete normalized result"),
                reference=response.headers.get("x-request-id"),
                units=credits,
                unit_cost_microusd=unit_cost,
                upstream_cost_microusd=credits * unit_cost,
            )
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


class MockAdapter:
    async def execute(
        self,
        service: ServiceDefinition,
        input_data: dict[str, Any],
        *,
        context: ProviderExecutionContext | None = None,
    ) -> ProviderResult:
        del context
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
    if service.provider.name == "gdelt":
        return GdeltAdapter()
    raise ProviderUnavailable("No provider adapter is configured")
