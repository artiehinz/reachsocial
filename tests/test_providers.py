from reachsocial.catalog import InputField, ProviderConfig, ServiceDefinition
from reachsocial.providers import ScrapeCreatorsAdapter


def service(service_id: str) -> ServiceDefinition:
    return ServiceDefinition(
        id=service_id,
        title="Test service",
        platform="Instagram",
        description="Test service",
        input_fields=[InputField(name="url", description="URL", format="url")],
        provider=ProviderConfig(name="scrapecreators"),
    )


def test_scrapecreators_profile_request_uses_a_handle() -> None:
    url, params = ScrapeCreatorsAdapter.request_for(
        service("instagram.profile"), {"url": "https://instagram.com/nasa"}
    )

    assert url == "https://api.scrapecreators.com/v1/instagram/profile"
    assert params == {"handle": "nasa"}


def test_scrapecreators_post_request_never_downloads_media() -> None:
    url, params = ScrapeCreatorsAdapter.request_for(
        service("instagram.post"), {"url": "https://instagram.com/reel/ABC123"}
    )

    assert url == "https://api.scrapecreators.com/v1/instagram/post"
    assert params == {
        "url": "https://instagram.com/reel/ABC123",
        "download_media": "false",
    }
