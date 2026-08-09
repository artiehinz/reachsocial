import httpx

from reachsocial.catalog import InputField, ProviderConfig, ServiceDefinition
from reachsocial.errors import PrivateOrUnavailable, ProviderAccessDenied
from reachsocial.normalized import normalize_provider_payload
from reachsocial.providers import ApifyAdapter, ScrapeCreatorsAdapter, _http_error


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


def test_scrapecreators_routes_cover_x_and_tiktok() -> None:
    _, x_params = ScrapeCreatorsAdapter.request_for(
        service("x.profile"), {"url": "https://x.com/nasa"}
    )
    feed_url, feed_params = ScrapeCreatorsAdapter.request_for(
        service("tiktok.feed"),
        {"url": "https://tiktok.com/@nasa", "cursor": "cursor-2"},
    )

    assert x_params == {"handle": "nasa"}
    assert feed_url.endswith("/v3/tiktok/profile/videos")
    assert feed_params == {
        "handle": "nasa",
        "max_cursor": "cursor-2",
        "sort_by": "latest",
    }


def test_apify_payloads_are_service_specific() -> None:
    x_service = service("x.feed").model_copy(
        update={"provider": {"name": "apify", "actor_id": "apidojo~tweet-scraper"}}
    )
    linkedin_service = service("linkedin.profile").model_copy(
        update={"provider": {"name": "apify", "actor_id": "actor"}}
    )

    assert ApifyAdapter.payload_for(
        x_service, {"url": "https://x.com/nasa", "max_items": 20}
    )["searchTerms"] == ["from:nasa"]
    assert ApifyAdapter.payload_for(
        linkedin_service, {"url": "https://linkedin.com/in/example"}
    ) == {"profileUrls": ["https://linkedin.com/in/example"], "maxProfiles": 1}


def test_normalized_x_post_excludes_provider_payload() -> None:
    result = normalize_provider_payload(
        "x.post",
        "https://x.com/example/status/123",
        {
            "success": True,
            "credits_charged": 1,
            "rest_id": "123",
            "legacy": {
                "full_text": "Hello",
                "favorite_count": 9,
                "created_at": "Mon Jan 01 12:00:00 +0000 2024",
            },
            "core": {
                "user_results": {
                    "result": {"rest_id": "7", "legacy": {"screen_name": "example"}}
                }
            },
        },
    )

    assert result["item"]["platform_id"] == "123"
    assert result["item"]["text"] == "Hello"
    assert result["item"]["published_at"] == "2024-01-01T12:00:00Z"
    assert "credits_charged" not in str(result)
    assert "provider" not in str(result)


def test_normalized_nested_instagram_profile() -> None:
    result = normalize_provider_payload(
        "instagram.profile",
        "https://instagram.com/example",
        {
            "success": True,
            "data": {
                "user": {
                    "id": "42",
                    "username": "example",
                    "full_name": "Example Person",
                    "biography": "Public bio",
                    "profile_pic_url": "https://cdn.example/avatar.jpg",
                    "is_verified": True,
                    "is_private": False,
                    "edge_followed_by": {"count": 100},
                    "edge_follow": {"count": 10},
                    "edge_owner_to_timeline_media": {"count": 20},
                }
            },
        },
    )["profile"]
    assert result["platform_id"] == "42"
    assert result["handle"] == "example"
    assert result["display_name"] == "Example Person"
    assert result["counts"] == {"followers": 100, "following": 10, "content": 20}


def test_normalized_snake_case_tiktok_feed_and_media() -> None:
    result = normalize_provider_payload(
        "tiktok.feed",
        "https://tiktok.com/@example",
        {
            "aweme_list": [
                {
                    "aweme_id": "123",
                    "desc": "Video",
                    "create_time": 1_700_000_000,
                    "share_url": "https://tiktok.com/@example/video/123",
                    "video": {
                        "download_no_watermark_addr": {
                            "url_list": ["https://cdn.example/video.mp4"]
                        },
                        "cover": {"url_list": ["https://cdn.example/cover.jpg"]},
                        "duration": 12,
                    },
                    "statistics": {
                        "digg_count": 5,
                        "comment_count": 2,
                        "share_count": 1,
                        "play_count": 50,
                    },
                }
            ],
            "max_cursor": 1700000001,
            "has_more": 1,
        },
    )
    item = result["items"][0]
    assert item["media"][0]["url"] == "https://cdn.example/video.mp4"
    assert item["metrics"] == {"likes": 5, "comments": 2, "shares": 1, "views": 50}
    assert result["next_cursor"] == "1700000001"
    assert result["has_more"] is True


def test_provider_authorization_errors_are_not_content_privacy_errors() -> None:
    apify = httpx.Response(403, request=httpx.Request("POST", "https://api.apify.com"))
    scrapecreators = httpx.Response(
        403, request=httpx.Request("GET", "https://api.scrapecreators.com")
    )
    assert isinstance(_http_error("Apify", apify), ProviderAccessDenied)
    assert isinstance(_http_error("ScrapeCreators", scrapecreators), PrivateOrUnavailable)
