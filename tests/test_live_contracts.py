from __future__ import annotations

import os

import pytest

from reachsocial.catalog import load_catalog
from reachsocial.providers import adapter_for
from reachsocial.services import ExecutionService

LIVE_CASES = [
    ("instagram.profile", "REACHSOCIAL_LIVE_INSTAGRAM_PROFILE_URL"),
    ("instagram.post", "REACHSOCIAL_LIVE_INSTAGRAM_POST_URL"),
    ("instagram.feed", "REACHSOCIAL_LIVE_INSTAGRAM_FEED_URL"),
    ("instagram.highlight", "REACHSOCIAL_LIVE_INSTAGRAM_HIGHLIGHT_URL"),
    ("x.profile", "REACHSOCIAL_LIVE_X_PROFILE_URL"),
    ("x.post", "REACHSOCIAL_LIVE_X_POST_URL"),
    ("x.feed", "REACHSOCIAL_LIVE_X_FEED_URL"),
    ("tiktok.profile", "REACHSOCIAL_LIVE_TIKTOK_PROFILE_URL"),
    ("tiktok.feed", "REACHSOCIAL_LIVE_TIKTOK_FEED_URL"),
    ("tiktok.video", "REACHSOCIAL_LIVE_TIKTOK_VIDEO_URL"),
    ("linkedin.profile", "REACHSOCIAL_LIVE_LINKEDIN_PROFILE_URL"),
    ("youtube.channel", "REACHSOCIAL_LIVE_YOUTUBE_CHANNEL_URL"),
    ("youtube.video", "REACHSOCIAL_LIVE_YOUTUBE_VIDEO_URL"),
    ("youtube.feed", "REACHSOCIAL_LIVE_YOUTUBE_FEED_URL"),
    ("facebook.profile", "REACHSOCIAL_LIVE_FACEBOOK_PROFILE_URL"),
    ("reddit.post", "REACHSOCIAL_LIVE_REDDIT_POST_URL"),
]


@pytest.mark.live_contract
@pytest.mark.asyncio
@pytest.mark.parametrize(("service_id", "url_variable"), LIVE_CASES)
async def test_live_provider_contract(service_id: str, url_variable: str) -> None:
    if os.getenv("REACHSOCIAL_LIVE_CONTRACTS") != "1":
        pytest.skip("Paid live contracts require REACHSOCIAL_LIVE_CONTRACTS=1")
    url = os.getenv(url_variable)
    if not url:
        pytest.skip(f"{url_variable} is not configured")
    service = load_catalog().by_id(service_id)
    assert service is not None
    input_data: dict[str, object] = {"url": url}
    if any(field.name == "max_items" for field in service.input_fields):
        input_data["max_items"] = 5
    ExecutionService.validate_input(service, input_data)
    result = await adapter_for(service).execute(service, input_data)
    assert result.data
    assert set(result.data).issubset({"profile", "item", "items", "next_cursor", "has_more"})
    assert result.upstream_cost_microusd >= 0


@pytest.mark.live_contract
@pytest.mark.asyncio
async def test_live_person_news_contract() -> None:
    if os.getenv("REACHSOCIAL_LIVE_CONTRACTS") != "1":
        pytest.skip("Paid live contracts require REACHSOCIAL_LIVE_CONTRACTS=1")
    full_name = os.getenv("REACHSOCIAL_LIVE_PERSON_NEWS_NAME")
    if not full_name:
        pytest.skip("REACHSOCIAL_LIVE_PERSON_NEWS_NAME is not configured")
    service = load_catalog().by_id("news.person")
    assert service is not None
    input_data: dict[str, object] = {"full_name": full_name, "max_items": 5}
    ExecutionService.validate_input(service, input_data)
    result = await adapter_for(service).execute(service, input_data)
    assert set(result.data) == {"articles", "countries"}
    assert result.upstream_cost_microusd == 0
