import pytest

from reachsocial.normalized import normalize_provider_payload, normalized_result_is_complete


@pytest.mark.parametrize("path", ["playAddr", "downloadAddr"])
def test_tiktok_nested_media_keeps_poster_author_and_stats(path):
    item = normalize_provider_payload(
        "tiktok.video",
        "https://www.tiktok.com/@creator/video/123",
        {
            "aweme_detail": {
                "aweme_id": "123",
                "desc": "Caption",
                "author": {
                    "uid": "42",
                    "unique_id": "creator",
                    "avatar_medium": {"url_list": ["https://cdn.example/avatar.jpg"]},
                },
                "video": {
                    path: {"url_list": ["https://cdn.example/clip.mp4"]},
                    "cover": {"url_list": ["https://cdn.example/poster.jpg"]},
                },
                "stats": {"diggCount": 0, "commentCount": 2, "playCount": 99, "shareCount": 3},
            }
        },
    )["item"]
    assert item["type"] == "video"
    assert item["media"][0]["url"] == "https://cdn.example/clip.mp4"
    assert item["media"][0]["preview_url"] == "https://cdn.example/poster.jpg"
    assert item["author"]["platform_id"] == "42"
    assert item["author"]["handle"] == "creator"
    assert item["author"]["avatar_url"] == "https://cdn.example/avatar.jpg"
    assert item["metrics"] == dict(likes=0, comments=2, views=99, shares=3)


def test_tiktok_photo_slideshow_and_missing_feed_permalink():
    item = normalize_provider_payload(
        "tiktok.feed",
        "https://www.tiktok.com/@creator",
        {
            "aweme_list": [
                {
                    "aweme_id": "123",
                    "author": {"unique_id": "creator"},
                    "image_post_info": {
                        "images": [
                            {"display_image": {"url_list": [f"https://cdn.example/{i}.jpg"]}}
                            for i in range(2)
                        ]
                    },
                }
            ]
        },
    )["items"][0]
    assert item["type"] == "carousel"
    assert len(item["media"]) == 2
    assert item["canonical_url"] == "https://www.tiktok.com/@creator/photo/123"


@pytest.mark.parametrize("service", ["tiktok.video", "tiktok.feed"])
@pytest.mark.parametrize("url_key", ["url_list", "urlList"])
def test_tiktok_uses_supplied_jpeg_cover_instead_of_first_heic_variant(service, url_key):
    jpeg = "https://cdn.example/cover.jpeg?x-signature=jpeg-signature&x-expires=123"
    post = {
        "aweme_id": "123",
        "video": {
            "playAddr": "https://cdn.example/video.mp4",
            "cover": {url_key: [{"invalid": True}, "https://cdn.example/cover.image", jpeg]},
        },
    }
    result = normalize_provider_payload(
        service,
        "https://www.tiktok.com/@creator/video/123",
        {"aweme_detail": post} if service == "tiktok.video" else {"aweme_list": [post]},
    )
    item = result["item"] if service == "tiktok.video" else result["items"][0]
    assert item["media"][0]["preview_url"] == jpeg


def test_tiktok_photo_slides_prefer_browser_images_without_rewriting_urls():
    result = normalize_provider_payload(
        "tiktok.video",
        "https://www.tiktok.com/@creator/photo/123",
        {
            "aweme_detail": {
                "aweme_id": "123",
                "image_post_info": {
                    "images": [
                        {
                            "display_image": {
                                "url_list": [
                                    "https://cdn.example/photo.image",
                                    "https://cdn.example/photo.webp?signature=kept",
                                ]
                            }
                        }
                    ]
                },
            }
        },
    )
    assert result["item"]["media"][0]["url"] == "https://cdn.example/photo.webp?signature=kept"


def test_x_uses_stable_author_id_and_retains_quotes_and_bookmarks():
    item = normalize_provider_payload(
        "x.feed",
        "https://x.com/creator",
        {
            "tweets": [
                {
                    "rest_id": "123",
                    "core": {
                        "user_results": {
                            "result": {
                                "id": "opaque-graphql-id",
                                "rest_id": "42",
                                "legacy": {"screen_name": "creator"},
                            }
                        }
                    },
                    "legacy": {"full_text": "Post", "quote_count": 2, "bookmark_count": 0},
                }
            ]
        },
    )["items"][0]
    assert item["canonical_url"] == "https://x.com/creator/status/123"
    assert item["author"]["platform_id"] == "42"
    assert item["metrics"]["quotes"] == 2
    assert item["metrics"]["bookmarks"] == 0


def test_x_selects_mp4_not_hls_and_does_not_treat_poster_as_video():
    def normalize(variants):
        return normalize_provider_payload(
            "x.post",
            "https://x.com/creator/status/1",
            {
                "rest_id": "1",
                "legacy": {
                    "extended_entities": {
                        "media": [
                            {
                                "type": "video",
                                "media_url_https": "https://cdn.example/poster.jpg",
                                "video_info": {"variants": variants},
                            }
                        ]
                    }
                },
            },
        )["item"]["media"][0]

    hls = {
        "content_type": "application/x-mpegURL",
        "url": "https://cdn.example/stream.m3u8",
        "bitrate": 9999,
    }
    mp4 = {"content_type": "video/mp4", "url": "https://cdn.example/clip.mp4", "bitrate": 100}
    assert normalize([hls, mp4])["url"] == mp4["url"]
    assert normalize([hls])["url"] is None
    assert normalize([hls])["preview_url"].endswith("poster.jpg")


@pytest.mark.parametrize(
    "service,payload",
    [
        ("youtube.video", {"id": "video-id", "title": "Video title"}),
        ("tiktok.video", {"aweme_id": "video-id", "desc": "Caption"}),
        ("instagram.post", {"id": "post-id", "caption": "Caption"}),
    ],
)
def test_absent_author_never_borrows_post_identity(service, payload):
    author = normalize_provider_payload(service, "https://example.com/post", payload)["item"][
        "author"
    ]
    assert author["platform_id"] is None
    assert author["handle"] is None


def test_youtube_channel_id_url_is_not_a_handle():
    profile = normalize_provider_payload(
        "youtube.channel",
        "https://www.youtube.com/channel/UC123",
        {"channelId": "UC123", "name": "Creator"},
    )["profile"]
    assert profile["handle"] is None
    assert profile["platform_id"] == "UC123"
    assert normalized_result_is_complete("youtube.channel", {"profile": profile})


def test_linkedin_handle_only_matches_consumer_contract():
    result = normalize_provider_payload(
        "linkedin.profile",
        "https://www.linkedin.com/in/creator/",
        {"items": [{"name": "Creator", "publicIdentifier": "creator"}]},
    )
    assert normalized_result_is_complete("linkedin.profile", result)


def test_linkedin_scrapecreators_public_profile_keeps_missing_enrichment_empty():
    result = normalize_provider_payload(
        "linkedin.profile",
        "https://linkedin.com/in/creator",
        {"id": "42", "name": "Creator", "about": "Public bio", "recentPosts": []},
    )
    assert result["profile"]["platform"] == "LinkedIn"
    assert result["profile"]["fields"]["experience"] == []
    assert result["profile"]["fields"]["education"] == []


def test_facebook_reddit_and_highlight_normalization_have_stable_envelopes():
    facebook = normalize_provider_payload(
        "facebook.profile", "https://facebook.com/creator", {"id": "42", "name": "Creator"}
    )
    reddit = normalize_provider_payload(
        "reddit.post",
        "https://reddit.com/comments/abc123",
        {"id": "abc123", "title": "A post", "author": "creator", "score": 4},
    )
    highlight = normalize_provider_payload(
        "instagram.highlight",
        "https://instagram.com/stories/highlights/17968483024692630",
        {"items": [{"id": "story-1", "caption": "Saved story"}]},
    )

    assert normalized_result_is_complete("facebook.profile", facebook)
    assert normalized_result_is_complete("reddit.post", reddit)
    assert reddit["item"]["metrics"]["likes"] == 4
    assert reddit["item"]["author"]["handle"] == "creator"
    assert reddit["item"]["author"]["platform_id"] is None
    assert highlight["profile"] is None
    assert len(highlight["items"]) == 1


@pytest.mark.parametrize("author", ["creator", "[deleted]", None, {}, "bad/name"])
def test_reddit_gallery_does_not_become_the_author(author):
    item = normalize_provider_payload(
        "reddit.post",
        "https://reddit.com/comments/abc123",
        {
            "id": "abc123", "name": "t3_abc123", "title": "Gallery post",
            "url": "https://www.reddit.com/gallery/abc123",
            "author": author, "author_fullname": "t2_user123",
        },
    )["item"]
    assert item["platform_id"] == "abc123"
    assert item["author"] == {
        "platform_id": "t2_user123" if author == "creator" else None,
        "handle": "creator" if author == "creator" else None,
        "display_name": None,
        "avatar_url": None,
        "verified": None,
        "canonical_url": "https://www.reddit.com/user/creator/" if author == "creator" else None,
    }


@pytest.mark.parametrize(
    "service,url",
    [
        ("instagram.profile", "https://www.instagram.com/creator/"),
        ("linkedin.profile", "https://www.linkedin.com/in/creator/"),
        ("tiktok.profile", "https://www.tiktok.com/@creator"),
    ],
)
def test_request_handle_alone_does_not_make_empty_profile_complete(service, url):
    result = normalize_provider_payload(service, url, {})
    assert not normalized_result_is_complete(service, result)


def test_instagram_channel_is_a_valid_handle_not_a_youtube_path():
    result = normalize_provider_payload(
        "instagram.profile", "https://www.instagram.com/channel/", {"id": "42"}
    )
    assert result["profile"]["handle"] == "channel"


def test_malformed_media_candidate_does_not_mask_valid_url_fallback():
    item = normalize_provider_payload(
        "tiktok.video",
        "https://www.tiktok.com/@creator/video/123",
        {
            "aweme_detail": {
                "aweme_id": "123",
                "video": {
                    "downloadAddr": {"unsupported": True},
                    "playAddr": "https://cdn.example/clip.mp4",
                    "cover": {"url_list": ["https://cdn.example/poster.jpg"]},
                },
            }
        },
    )["item"]
    assert item["media"][0]["url"] == "https://cdn.example/clip.mp4"
