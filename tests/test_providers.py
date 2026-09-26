import httpx
import pytest

from reachsocial.catalog import InputField, ProviderConfig, ServiceDefinition
from reachsocial.errors import (
    PrivateOrUnavailable,
    ProviderAccessDenied,
    ProviderTimeout,
    ProviderUnavailable,
)
from reachsocial.normalized import (
    normalize_provider_payload,
    normalized_result_is_complete,
)
from reachsocial.providers import (
    ApifyAdapter,
    GdeltAdapter,
    ProviderExecutionContext,
    ScrapeCreatorsAdapter,
    _http_error,
)


def test_gdelt_person_news_request_is_exact_and_bounded() -> None:
    params = GdeltAdapter.request_params({"full_name": '  Lionel "Messi"  ', "max_items": 999})

    assert params == {
        "query": '"Lionel Messi"',
        "mode": "ArtList",
        "format": "JSON",
        "maxrecords": 100,
        "sort": "DateDesc",
    }


def test_gdelt_person_news_normalization_drops_unsafe_and_duplicate_urls() -> None:
    data = GdeltAdapter._normalized_data(
        {
            "articles": [
                {
                    "title": " Messi wins again ",
                    "url": "https://news.example/story",
                    "socialimage": "https://images.example/messi.jpg",
                    "domain": "news.example",
                    "language": "English",
                    "sourcecountry": "United States",
                    "seendate": "20260812T010000Z",
                },
                {
                    "title": "Duplicate",
                    "url": "https://news.example/story",
                    "sourcecountry": "United States",
                },
                {
                    "title": "Unsafe",
                    "url": "javascript:alert(1)",
                    "sourcecountry": "Spain",
                },
            ]
        },
        max_items=10,
    )

    assert data["articles"] == [
        {
            "title": "Messi wins again",
            "url": "https://news.example/story",
            "image": "https://images.example/messi.jpg",
            "domain": "news.example",
            "published_at": "20260812T010000Z",
            "language": "English",
            "country": "United States",
            "country_code": "US",
        }
    ]
    assert data["countries"] == [{"code": "US", "name": "United States", "count": 1}]


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


def test_scrapecreators_routes_cover_profile_feeds_and_youtube() -> None:
    instagram_url, instagram_params = ScrapeCreatorsAdapter.request_for(
        service("instagram.feed"), {"url": "https://instagram.com/nasa"}
    )
    x_url, x_params = ScrapeCreatorsAdapter.request_for(
        service("x.feed"), {"url": "https://x.com/nasa"}
    )
    channel_url, channel_params = ScrapeCreatorsAdapter.request_for(
        service("youtube.channel"), {"url": "https://youtube.com/@NASA"}
    )
    feed_url, feed_params = ScrapeCreatorsAdapter.request_for(
        service("youtube.feed"), {"url": "https://youtube.com/channel/UC1234567890"}
    )
    video_url, video_params = ScrapeCreatorsAdapter.request_for(
        service("youtube.video"),
        {"url": "https://youtube.com/watch?v=dQw4w9WgXcQ"},
    )

    assert instagram_url.endswith("/v2/instagram/user/posts")
    assert instagram_params == {"handle": "nasa"}
    assert x_url.endswith("/v1/twitter/user-tweets")
    assert x_params == {"handle": "nasa"}
    assert channel_url.endswith("/v1/youtube/channel")
    assert channel_params == {"handle": "NASA"}
    assert feed_url.endswith("/v1/youtube/channel-videos")
    assert feed_params == {
        "channelId": "UC1234567890",
        "sort": "latest",
        "includeExtras": "true",
    }
    assert video_url.endswith("/v1/youtube/video")
    assert video_params == {"url": "https://youtube.com/watch?v=dQw4w9WgXcQ"}


def test_apify_payloads_are_service_specific() -> None:
    x_service = service("x.feed").model_copy(
        update={"provider": {"name": "apify", "actor_id": "apidojo~tweet-scraper"}}
    )
    linkedin_service = service("linkedin.profile").model_copy(
        update={"provider": {"name": "apify", "actor_id": "actor"}}
    )

    assert ApifyAdapter.payload_for(x_service, {"url": "https://x.com/nasa", "max_items": 20})[
        "searchTerms"
    ] == ["from:nasa"]
    assert ApifyAdapter.payload_for(
        linkedin_service, {"url": "https://linkedin.com/in/example"}
    ) == {"profileUrls": ["https://linkedin.com/in/example"], "maxProfiles": 1}


def apify_service(service_id: str, *, cap: int = 10_000) -> ServiceDefinition:
    response_shape = "feed" if service_id == "x.feed" else "profile"
    fields = [InputField(name="url", description="URL", format="url")]
    if service_id == "x.feed":
        fields.append(
            InputField(
                name="max_items",
                description="Maximum items",
                required=False,
                format="integer",
                default=20,
                minimum=1,
                maximum=100,
            )
        )
    return ServiceDefinition(
        id=service_id,
        title="Test service",
        platform="X" if service_id == "x.feed" else "LinkedIn",
        description="Test service",
        input_fields=fields,
        provider=ProviderConfig(
            name="apify",
            actor_id="test~actor",
            max_total_charge_microusd=cap,
        ),
        execution="async",
        response_shape=response_shape,
        timeout_seconds=120,
        retries=0,
    )


def apify_response(data: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": data},
        request=httpx.Request("GET", "https://api.apify.com"),
    )


class SequenceApifyAdapter(ApifyAdapter):
    poll_interval_seconds = 0
    cost_stabilization_seconds = 0

    def __init__(self, responses: list[object]) -> None:
        super().__init__("protected-token")
        self.responses = responses
        self.calls: list[tuple[str, str, dict]] = []

    async def _request(self, client, method: str, url: str, **kwargs):
        del client
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.asyncio
async def test_apify_start_is_capped_bounded_and_cost_is_stable() -> None:
    items = [
        {"id": str(index), "url": f"https://x.com/NASA/status/{index}", "text": "Post"}
        for index in range(6)
    ]
    adapter = SequenceApifyAdapter(
        [
            apify_response({"id": "run-one", "status": "RUNNING", "defaultDatasetId": "ds"}),
            ProviderTimeout("temporary poll timeout"),
            apify_response(
                {
                    "id": "run-one",
                    "status": "SUCCEEDED",
                    "defaultDatasetId": "ds",
                    "usageTotalUsd": "0.001",
                }
            ),
            apify_response(
                {
                    "id": "run-one",
                    "status": "SUCCEEDED",
                    "defaultDatasetId": "ds",
                    "usageTotalUsd": "0.002000",
                }
            ),
            httpx.Response(
                200,
                json=items,
                request=httpx.Request("GET", "https://api.apify.com"),
            ),
        ]
    )
    references: list[str] = []
    result = await adapter.execute(
        apify_service("x.feed"),
        {"url": "https://x.com/NASA", "max_items": 5},
        context=ProviderExecutionContext(persist_reference=references.append),
    )

    start = adapter.calls[0]
    assert start[0] == "POST"
    assert start[2]["params"] == {
        "maxItems": "5",
        "maxTotalChargeUsd": "0.01",
        "timeout": "120",
    }
    assert start[2]["json"]["maxItems"] == 5
    assert references == ["run-one"]
    assert sum(method == "POST" and url.endswith("/runs") for method, url, _ in adapter.calls) == 1
    assert result.provider_reference == "run-one"
    assert result.upstream_cost_microusd == 2_000
    assert result.provider_units == 5
    assert len(result.data["items"]) == 5


@pytest.mark.asyncio
async def test_apify_resume_polls_existing_run_without_starting_another() -> None:
    adapter = SequenceApifyAdapter(
        [
            apify_response(
                {
                    "id": "run-existing",
                    "status": "SUCCEEDED",
                    "defaultDatasetId": "ds",
                    "usageTotalUsd": "0.018",
                }
            ),
            apify_response(
                {
                    "id": "run-existing",
                    "status": "SUCCEEDED",
                    "defaultDatasetId": "ds",
                    "usageTotalUsd": "0.018",
                }
            ),
            httpx.Response(
                200,
                json=[
                    {
                        "name": "Example Person",
                        "linkedinUrl": "https://linkedin.com/in/example",
                        "currentPositions": [{"title": "CEO", "company": "Example"}],
                    }
                ],
                request=httpx.Request("GET", "https://api.apify.com"),
            ),
        ]
    )
    result = await adapter.execute(
        apify_service("linkedin.profile", cap=50_000),
        {"url": "https://linkedin.com/in/example"},
        context=ProviderExecutionContext(existing_reference="run-existing"),
    )

    assert all(not url.endswith("/runs") for _, url, _ in adapter.calls)
    assert adapter.calls[0][1].endswith("/actor-runs/run-existing")
    assert result.upstream_cost_microusd == 18_000
    assert result.data["profile"]["fields"]["experience"][0]["organization"] == "Example"


@pytest.mark.asyncio
async def test_apify_timeout_aborts_the_same_run(monkeypatch) -> None:
    adapter = SequenceApifyAdapter(
        [
            apify_response({"id": "run-timeout", "status": "RUNNING"}),
            apify_response({"id": "run-timeout", "status": "ABORTING"}),
        ]
    )
    adapter.cost_stabilization_grace_seconds = 0
    monotonic = iter([0.0, 121.0])
    monkeypatch.setattr(adapter, "_monotonic", lambda: next(monotonic))

    with pytest.raises(ProviderTimeout) as error:
        await adapter.execute(
            apify_service("x.feed"),
            {"url": "https://x.com/NASA", "max_items": 5},
        )

    assert error.value.provider_reference == "run-timeout"
    assert any(url.endswith("/actor-runs/run-timeout/abort") for _, url, _ in adapter.calls)
    assert sum(url.endswith("/runs") for _, url, _ in adapter.calls) == 1


def test_apify_charge_cap_is_required() -> None:
    with pytest.raises(ProviderUnavailable):
        ApifyAdapter.start_params(
            apify_service("x.feed", cap=0),
            {"url": "https://x.com/NASA", "max_items": 5},
        )


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
                "user_results": {"result": {"rest_id": "7", "legacy": {"screen_name": "example"}}}
            },
        },
    )

    assert result["item"]["platform_id"] == "123"
    assert result["item"]["text"] == "Hello"
    assert result["item"]["published_at"] == "2024-01-01T12:00:00Z"
    assert "credits_charged" not in str(result)
    assert "provider" not in str(result)


def test_normalized_current_instagram_post_envelope_is_consumer_complete() -> None:
    result = normalize_provider_payload(
        "instagram.post",
        "https://instagram.com/p/Current123",
        {
            "success": True,
            "credits_charged": 1,
            "data": {
                "xdt_shortcode_media": {
                    "id": "987654321",
                    "shortcode": "Current123",
                    "product_type": "clips",
                    "display_url": "https://cdn.example/preview.jpg",
                    "video_url": "https://cdn.example/video.mp4",
                    "video_duration": 12.5,
                    "video_play_count": 500,
                    "taken_at_timestamp": 1_700_000_000,
                    "comment_count": 7,
                    "edge_media_preview_like": {"count": 42},
                    "edge_media_to_caption": {"edges": [{"node": {"text": "Current caption"}}]},
                    "owner": {
                        "id": "123",
                        "username": "example",
                        "full_name": "Example Person",
                        "is_verified": False,
                    },
                }
            },
        },
    )

    item = result["item"]
    assert item["platform_id"] == "987654321"
    assert item["text"] == "Current caption"
    assert item["published_at"] == "2023-11-14T22:13:20Z"
    assert item["metrics"] == {
        "likes": 42,
        "comments": 7,
        "shares": None,
        "views": 500,
    }
    assert item["author"]["handle"] == "example"
    assert item["media"][0]["url"] == "https://cdn.example/video.mp4"
    assert normalized_result_is_complete("instagram.post", result)


def test_normalized_instagram_feed_uses_media_assets_not_post_permalink() -> None:
    result = normalize_provider_payload(
        "instagram.feed",
        "https://instagram.com/example",
        {
            "items": [
                {
                    "id": "987654321",
                    "code": "Current123",
                    "product_type": "carousel_container",
                    "url": "https://www.instagram.com/p/Current123/",
                    "display_uri": "https://cdn.example/carousel-cover.jpg",
                    "carousel_media": [
                        {
                            "id": "slide-video",
                            "video_versions": [
                                {"url": "https://cdn.example/slide.mp4"}
                            ],
                            "image_versions2": {
                                "candidates": [
                                    {"url": "https://cdn.example/slide-preview.jpg"}
                                ]
                            },
                        },
                        {
                            "id": "slide-image",
                            "display_uri": "https://cdn.example/slide.jpg",
                        },
                    ],
                    "owner": {"id": "123", "username": "example"},
                }
            ]
        },
    )

    item = result["items"][0]
    assert item["canonical_url"] == "https://instagram.com/p/Current123"
    assert item["media"] == [
        {
            "type": "video",
            "url": "https://cdn.example/slide.mp4",
            "preview_url": "https://cdn.example/slide-preview.jpg",
            "width": None,
            "height": None,
            "duration_seconds": None,
            "expires_at": None,
        },
        {
            "type": "image",
            "url": "https://cdn.example/slide.jpg",
            "preview_url": None,
            "width": None,
            "height": None,
            "duration_seconds": None,
            "expires_at": None,
        },
    ]
    assert item["type"] == "carousel"
    assert all(media["url"] != item["canonical_url"] for media in item["media"])
    assert normalized_result_is_complete("instagram.feed", result)


def test_incomplete_provider_success_cannot_cross_the_normalized_contract() -> None:
    result = normalize_provider_payload(
        "instagram.post",
        "https://instagram.com/p/Missing123",
        {"success": True, "credits_charged": 1, "data": {}},
    )

    assert not normalized_result_is_complete("instagram.post", result)


def test_normalized_apidojo_x_feed_fields() -> None:
    result = normalize_provider_payload(
        "x.feed",
        "https://x.com/NASA",
        {
            "items": [
                {
                    "type": "tweet",
                    "id": "123",
                    "url": "https://x.com/NASA/status/123",
                    "text": "Space update",
                    "createdAt": "Fri Nov 24 17:49:36 +0000 2023",
                    "likeCount": 10,
                    "replyCount": 2,
                    "retweetCount": 3,
                    "viewCount": 100,
                    "media": ["https://pbs.twimg.com/media/example.jpg"],
                    "author": {
                        "id": "42",
                        "userName": "NASA",
                        "name": "NASA",
                        "url": "https://x.com/NASA",
                        "isVerified": True,
                        "profilePicture": "https://pbs.twimg.com/profile_images/example.jpg",
                    },
                }
            ]
        },
    )["items"][0]

    assert result["author"]["handle"] == "NASA"
    assert result["author"]["verified"] is True
    assert result["published_at"] == "2023-11-24T17:49:36Z"
    assert result["metrics"] == {"likes": 10, "comments": 2, "shares": 3, "views": 100}
    assert result["media"][0]["url"] == "https://pbs.twimg.com/media/example.jpg"


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


def test_normalized_linkedin_candidate_fields() -> None:
    result = normalize_provider_payload(
        "linkedin.profile",
        "https://www.linkedin.com/in/example/",
        {
            "items": [
                {
                    "name": "Example Person",
                    "linkedinUrl": "https://www.linkedin.com/in/example/",
                    "headline": "Chief Example Officer",
                    "profileImageUrl": "https://cdn.example/profile.jpg",
                    "followerCount": 123,
                    "currentPositions": [
                        {"title": "CEO", "company": "Example", "startDate": "2020"}
                    ],
                    "education": [
                        {
                            "institution": "Example University",
                            "degree": "BS",
                            "startYear": 2000,
                            "endYear": 2004,
                        }
                    ],
                }
            ]
        },
    )["profile"]

    assert result["display_name"] == "Example Person"
    assert result["avatar_url"] == "https://cdn.example/profile.jpg"
    assert result["counts"]["followers"] == 123
    assert result["fields"]["experience"] == [
        {
            "title": "CEO",
            "organization": "Example",
            "location": None,
            "started_at": "2020-01-01T00:00:00Z",
            "ended_at": None,
            "description": None,
        }
    ]
    assert result["fields"]["education"][0]["school"] == "Example University"
    assert result["fields"]["education"][0]["started_at"] == "2000-01-01T00:00:00Z"


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


def test_normalized_youtube_channel_and_video_feed() -> None:
    profile = normalize_provider_payload(
        "youtube.channel",
        "https://youtube.com/@Example",
        {
            "channel": {
                "channelId": "UC1234567890",
                "channelHandle": "@Example",
                "channelTitle": "Example Channel",
                "description": "Channel bio",
                "avatar": {
                    "image": {
                        "sources": [
                            {"url": "https://cdn.example/avatar.jpg", "width": 900}
                        ]
                    }
                },
                "isVerified": True,
                "subscriberCountText": "2.9M subscribers",
                "videoCount": 123,
                "country": "US",
                "keywords": ["news", "video"],
            }
        },
    )["profile"]
    assert profile["platform_id"] == "UC1234567890"
    assert profile["handle"] == "Example"
    assert profile["display_name"] == "Example Channel"
    assert profile["avatar_url"] == "https://cdn.example/avatar.jpg"
    assert profile["verified"] is True
    assert profile["counts"]["followers"] == 2_900_000
    assert profile["fields"]["keywords"] == ["news", "video"]

    result = normalize_provider_payload(
        "youtube.feed",
        "https://youtube.com/@Example",
        {
            "videos": [
                {
                    "videoId": "dQw4w9WgXcQ",
                    "title": "Example video",
                    "description": "Description",
                    "thumbnailUrl": "https://cdn.example/thumb.jpg",
                    "viewCountText": "1.8B views",
                    "likeCountText": "19.3M",
                    "commentCountText": "2.4M comments",
                    "channel": {
                        "channelId": "UC1234567890",
                        "channelHandle": "@Example",
                        "channelTitle": "Example Channel",
                        "avatar": {"url": "https://cdn.example/avatar.jpg"},
                    },
                }
            ],
            "continuationToken": "next-page",
        },
    )
    item = result["items"][0]
    assert item["canonical_url"] == "https://youtube.com/watch?v=dQw4w9WgXcQ"
    assert item["platform_id"] == "dQw4w9WgXcQ"
    assert item["type"] == "video"
    assert item["author"]["handle"] == "Example"
    assert item["media"][0]["url"] == "https://cdn.example/thumb.jpg"
    assert item["metrics"] == {
        "likes": 19_300_000,
        "comments": 2_400_000,
        "shares": None,
        "views": 1_800_000_000,
    }
    assert result["next_cursor"] == "next-page"
    assert result["has_more"] is True


def test_provider_authorization_errors_are_not_content_privacy_errors() -> None:
    apify = httpx.Response(403, request=httpx.Request("POST", "https://api.apify.com"))
    scrapecreators = httpx.Response(
        403, request=httpx.Request("GET", "https://api.scrapecreators.com")
    )
    assert isinstance(_http_error("Apify", apify), ProviderAccessDenied)
    assert isinstance(_http_error("ScrapeCreators", scrapecreators), PrivateOrUnavailable)


def test_instagram_mobile_feed_caption_counts_author_and_media_type():
    result = normalize_provider_payload("instagram.feed", "https://instagram.com/example", {
        "items": [{
            "id": "123", "code": "Example123", "product_type": "clips",
            "caption": {"text": "Full caption\nwith a second line"},
            "like_count": 0, "comment_count": 2, "play_count": 1234,
            "user": {"username": "example", "full_name": "Example Author"},
            "video_versions": [{"url": "https://cdn.example/video.mp4"}],
            "image_versions2": {"candidates": [{"url": "https://cdn.example/poster.jpg"}]},
        }]
    })
    item = result["items"][0]
    assert item["text"] == "Full caption\nwith a second line"
    assert item["metrics"]["likes"] == 0
    assert item["metrics"]["views"] == 1234
    assert item["author"]["handle"] == "example"
    assert item["type"] == "video"
    assert len(item["media"]) == 1
    assert item["media"][0]["preview_url"] == "https://cdn.example/poster.jpg"
