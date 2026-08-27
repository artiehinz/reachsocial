import pytest
from pydantic import ValidationError

from reachsocial.catalog import InputField, ProviderConfig, ServiceDefinition, load_catalog


def apify_definition(**updates) -> ServiceDefinition:
    values = {
        "id": "x.feed",
        "title": "X Feed",
        "platform": "X",
        "description": "Latest feed",
        "input_fields": [InputField(name="url", description="URL", format="url")],
        "provider": ProviderConfig(name="apify", actor_id="test~actor"),
        "execution": "async",
        "response_shape": "feed",
        "enabled": True,
        "public": False,
        "retries": 0,
    }
    values.update(updates)
    return ServiceDefinition(**values)


def test_enabled_apify_service_requires_a_charge_cap() -> None:
    with pytest.raises(ValidationError, match="positive charge cap"):
        apify_definition()


def test_enabled_apify_service_rejects_automatic_run_retries() -> None:
    with pytest.raises(ValidationError, match="replacement runs"):
        apify_definition(
            provider=ProviderConfig(
                name="apify",
                actor_id="test~actor",
                max_total_charge_microusd=10_000,
            ),
            retries=1,
        )


def test_public_price_is_checked_against_the_hard_cost_cap() -> None:
    with pytest.raises(ValidationError, match="50% gross margin"):
        apify_definition(
            provider=ProviderConfig(
                name="apify",
                actor_id="test~actor",
                max_total_charge_microusd=40_000,
            ),
            estimated_upstream_cost_microusd=40_000,
            enabled=True,
            public=True,
            price_cents=5,
        )


def test_repository_catalog_passes_release_safety_validation() -> None:
    catalog = load_catalog()
    news = catalog.by_id("news.person")
    assert news.enabled is True
    assert news.public is False
    assert news.provider.name == "gdelt"
    assert news.response_shape == "news"
    assert news.status == "private"
    x_feed = catalog.by_id("x.feed")
    assert x_feed.enabled is True
    assert x_feed.public is False
    assert x_feed.provider.name == "scrapecreators"
    assert x_feed.status == "private"
    linkedin = catalog.by_id("linkedin.profile")
    assert linkedin.enabled is True
    assert linkedin.public is True
    assert linkedin.cost_verified is True
    assert linkedin.price_cents == 10
    assert linkedin.status == "available"
    assert load_catalog().by_id("x.profile").status == "private"
    assert load_catalog().by_id("instagram.stories").status == "paused"


def test_available_catalog_status_cannot_advertise_a_disabled_service() -> None:
    with pytest.raises(ValidationError, match="available catalog service"):
        ServiceDefinition(
            id="youtube.video",
            title="YouTube video",
            platform="YouTube",
            description="Video metadata",
            input_fields=[InputField(name="url", description="URL", format="url")],
            provider=ProviderConfig(name="mock"),
            catalog_status="available",
        )


def test_private_catalog_status_requires_enabled_non_public_service() -> None:
    with pytest.raises(ValidationError, match="private catalog service"):
        ServiceDefinition(
            id="news.person",
            title="Person news",
            platform="News",
            description="News",
            input_fields=[InputField(name="full_name", description="Name")],
            provider=ProviderConfig(name="gdelt"),
            catalog_status="private",
        )
