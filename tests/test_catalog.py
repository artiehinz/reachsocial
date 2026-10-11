import pytest
from pydantic import ValidationError

from reachsocial.catalog import InputField, ProviderConfig, ServiceDefinition, load_catalog


def test_public_price_is_checked_against_the_maximum_attempt_cost() -> None:
    with pytest.raises(ValidationError, match="50% gross margin"):
        ServiceDefinition(
            id="x.feed",
            title="X Feed",
            platform="X",
            description="Feed",
            input_fields=[InputField(name="url", description="URL", format="url")],
            provider=ProviderConfig(name="scrapecreators"),
            enabled=True,
            public=True,
            estimated_upstream_cost_microusd=40_000,
            provider_unit_cost_microusd=40_000,
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
    assert linkedin.enabled is False
    assert linkedin.public is False
    assert linkedin.cost_verified is True
    assert linkedin.price_cents == 10
    assert linkedin.status == "validation"
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
