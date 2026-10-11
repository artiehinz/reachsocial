import pytest

from reachsocial.errors import InvalidInput
from reachsocial.normalizer import resolve_url, validate_service_url


def test_resolve_x_status_url_and_remove_tracking() -> None:
    result = resolve_url("https://twitter.com/example/status/123?utm_source=test&fbclid=remove")
    assert result == {
        "platform": "X",
        "resource_type": "post",
        "canonical_url": "https://x.com/example/status/123",
        "service_id": "x.post",
    }


def test_reject_unsupported_url() -> None:
    with pytest.raises(InvalidInput):
        resolve_url("https://example.com/nope")


def test_resolve_story_url_to_canonical_profile() -> None:
    result = resolve_url("https://instagram.com/stories/openai/123")
    assert result["service_id"] == "instagram.stories"
    assert result["canonical_url"] == "https://instagram.com/openai"


def test_resolve_saved_highlight_url() -> None:
    assert resolve_url("https://www.instagram.com/stories/highlights/17968483024692630/") == {
        "platform": "Instagram",
        "resource_type": "highlight",
        "canonical_url": "https://instagram.com/stories/highlights/17968483024692630",
        "service_id": "instagram.highlight",
    }


@pytest.mark.parametrize(
    ("raw_url", "service_id", "canonical_url"),
    (
        ("instagram.com/openai/", "instagram.profile", "https://instagram.com/openai"),
        (
            "https://www.instagram.com/reel/ABC123/?igshid=gone",
            "instagram.post",
            "https://instagram.com/reel/ABC123",
        ),
        ("https://mobile.twitter.com/openai", "x.profile", "https://x.com/openai"),
        (
            "https://x.com/openai/status/123456789",
            "x.post",
            "https://x.com/openai/status/123456789",
        ),
        ("https://m.tiktok.com/@openai", "tiktok.profile", "https://tiktok.com/@openai"),
        (
            "https://www.tiktok.com/@openai/video/7351028156295566638",
            "tiktok.video",
            "https://tiktok.com/@openai/video/7351028156295566638",
        ),
        (
            "https://m.linkedin.com/in/example-person/?trk=public_profile",
            "linkedin.profile",
            "https://linkedin.com/in/example-person",
        ),
        (
            "https://ca.linkedin.com/in/example-person",
            "linkedin.profile",
            "https://linkedin.com/in/example-person",
        ),
        (
            "https://youtu.be/dQw4w9WgXcQ?si=share",
            "youtube.video",
            "https://youtube.com/watch?v=dQw4w9WgXcQ",
        ),
        (
            "https://www.youtube.com/shorts/dQw4w9WgXcQ",
            "youtube.video",
            "https://youtube.com/watch?v=dQw4w9WgXcQ",
        ),
        (
            "https://www.youtube.com/@OpenAI/videos",
            "youtube.channel",
            "https://youtube.com/@OpenAI",
        ),
        (
            "https://youtube.com/channel/UC1234567890",
            "youtube.channel",
            "https://youtube.com/channel/UC1234567890",
        ),
        (
            "https://old.reddit.com/r/python/comments/abc123/example/",
            "reddit.post",
            "https://reddit.com/comments/abc123",
        ),
        ("https://redd.it/abc123", "reddit.post", "https://reddit.com/comments/abc123"),
        (
            "https://m.facebook.com/example.person",
            "facebook.profile",
            "https://facebook.com/example.person",
        ),
        (
            "https://facebook.com/profile.php?id=123456",
            "facebook.profile",
            "https://facebook.com/profile.php?id=123456",
        ),
    ),
)
def test_resolve_catalog_url_matrix(raw_url: str, service_id: str, canonical_url: str) -> None:
    assert resolve_url(raw_url) == {
        "platform": {
            "instagram": "Instagram",
            "x": "X",
            "tiktok": "TikTok",
            "linkedin": "LinkedIn",
            "youtube": "YouTube",
            "reddit": "Reddit",
            "facebook": "Facebook",
        }[service_id.split(".", 1)[0]],
        "resource_type": service_id.split(".", 1)[1],
        "canonical_url": canonical_url,
        "service_id": service_id,
    }


@pytest.mark.parametrize(
    "raw_url",
    (
        "https://instagram.com/stories/highlights/123456",
        "https://x.com/invalid-handle/status/123",
        "https://tiktok.com/@bad..handle",
        "https://linkedin.com/company/openai",
        "https://youtube.com/channel/not-a-channel-id",
        "https://reddit.com/r/python",
        "https://facebook.com/groups/example",
        "https://facebook.com/profile.php",
        "https://facebook.com/login",
    ),
)
def test_rejects_recognized_but_unsupported_url_shapes(raw_url: str) -> None:
    with pytest.raises(InvalidInput):
        resolve_url(raw_url)


def test_canonical_urls_normalize_case_and_discard_non_identity_query_data() -> None:
    assert resolve_url("https://X.com/OpenAI/STATUS/123?ref=share")["canonical_url"] == (
        "https://x.com/openai/status/123"
    )
    assert (
        resolve_url("https://facebook.com/profile.php?id=123&sk=about")["canonical_url"]
        == "https://facebook.com/profile.php?id=123"
    )


def test_service_validation_uses_the_same_resolution_contract() -> None:
    assert validate_service_url("x.feed", "twitter.com/openai") == "https://x.com/openai"
    assert validate_service_url("tiktok.feed", "tiktok.com/@openai") == "https://tiktok.com/@openai"
    assert (
        validate_service_url("instagram.feed", "instagram.com/openai")
        == "https://instagram.com/openai"
    )
    assert (
        validate_service_url("youtube.feed", "youtube.com/@OpenAI/videos")
        == "https://youtube.com/@OpenAI"
    )
    with pytest.raises(InvalidInput, match="instagram.profile"):
        validate_service_url("instagram.profile", "instagram.com/p/ABC123")
