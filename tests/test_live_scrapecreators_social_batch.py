from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "live_scrapecreators_social_batch.py"
_SPEC = importlib.util.spec_from_file_location("live_scrapecreators_social_batch", _SCRIPT)
assert _SPEC and _SPEC.loader
batch = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(batch)


def test_bounded_batch_covers_the_requested_first_product_slice() -> None:
    ids = {case[0] for case in batch.CASES}
    assert {
        "instagram.profile",
        "instagram.profile_posts",
        "instagram.search",
        "x.profile",
        "x.post",
        "x.user_tweets",
        "tiktok.profile",
        "tiktok.video",
        "tiktok.feed",
        "tiktok.user_search",
        "youtube.channel",
        "youtube.video",
        "youtube.channel_videos",
        "youtube.search",
    }.issubset(ids)


def test_named_case_selection_is_limited_to_the_bounded_batch() -> None:
    selected = tuple(case for case in batch.CASES if case[0] in {"x.post", "youtube.search"})
    assert [case[0] for case in selected] == ["x.post", "youtube.search"]
    assert [case[0] for case in batch.FOLLOW_UP_CASES] == [
        "instagram.nikefootball_profile",
        "instagram.nikefootball_search",
        "tiktok.stoolpresidente_profile",
        "youtube.rickastley_channel",
    ]


def test_report_shape_is_sanitized_and_never_preserves_provider_payload_values() -> None:
    result = batch._shape(
        {"success": True, "credits_charged": 1, "items": [{"private": "raw value"}]},
        ("items",),
    )
    assert result["json_object"] is True
    assert result["expected_keys_present"] is True
    assert result["list_counts"] == {"items": 1}
    assert "raw value" not in repr(result)


def test_ui_fixture_keeps_presentation_fields_without_ids_or_urls() -> None:
    fixture = batch._ui_fixture(
        "instagram.post",
        {
            "success": True,
            "data": {
                "id": "provider-private-id",
                "caption": "A public caption https://provider.example/private-token",
                "owner": {"username": "example", "full_name": "Example creator"},
                "display_url": "https://provider.example/media/private-token",
                "likes_count": 14,
            },
        },
    )
    assert fixture["kind"] == "post"
    assert fixture["item"]["author"]["handle"] == "example"
    assert fixture["item"]["caption"] == "A public caption [link]"
    assert "provider-private-id" not in repr(fixture)
    assert "private-token" not in repr(fixture)


def test_safe_text_never_stringifies_a_provider_mapping() -> None:
    assert batch._safe_text({"private_id": "provider-private-id"}) is None


def test_safe_count_accepts_provider_display_counts() -> None:
    assert batch._safe_count("1.2M views") == 1_200_000
    assert batch._safe_count("4,321") == 4_321
    assert batch._safe_count("hidden") is None


def test_instagram_profile_preserves_nested_public_counts() -> None:
    fixture = batch._ui_fixture(
        "instagram.profile",
        {
            "data": {
                "user": {
                    "username": "example",
                    "edge_followed_by": {"count": 31},
                    "edge_follow": {"count": 7},
                    "edge_owner_to_timeline_media": {"count": 14},
                }
            }
        },
    )
    assert fixture["profile"]["counts"] == {"followers": 31, "following": 7, "content": 14}


def test_tiktok_media_candidates_prefer_the_video_source_when_requested() -> None:
    assert batch._media_candidate_priority("cover", prefer_video=True) == 1
    assert batch._media_candidate_priority("video.download_addr", prefer_video=True) == 0
    selected = batch._selected_media_candidates(
        "tiktok.video",
        [("https://provider.example/video.mp4", "video.download_addr"), ("https://provider.example/cover.jpg", "cover")],
        prefer_video=True,
    )
    assert selected == [
        ("https://provider.example/video.mp4", "video.download_addr"),
        ("https://provider.example/cover.jpg", "cover"),
    ]


def test_ui_post_finds_nested_metrics_and_additional_counters() -> None:
    post = batch._ui_post(
        {
            "aweme_info": {
                "author": {"unique_id": "creator", "nickname": "Creator"},
                "stats": {
                    "diggCount": 12,
                    "commentCount": 3,
                    "shareCount": 4,
                    "playCount": 55,
                    "collectCount": 6,
                },
            }
        }
    )

    assert post["author"]["handle"] == "creator"
    assert post["metrics"] == {
        "likes": 12,
        "comments": 3,
        "shares": 4,
        "views": 55,
        "bookmarks": 6,
        "quotes": None,
    }


def test_ui_profile_keeps_bounded_public_categories_and_tags() -> None:
    profile = batch._ui_profile(
        {
            "username": "creator",
            "category_name": "Video creator",
            "tags": ["Comedy", "Lifestyle"],
        }
    )

    assert profile["categories"] == ["Video creator"]
    assert profile["tags"] == ["Comedy", "Lifestyle"]


def test_ui_profile_splits_and_deduplicates_provider_tags() -> None:
    profile = batch._ui_profile(
        {
            "username": "creator",
            "keywords": "Music, Pop, music, 3",
            "tags": "Official, Pop",
        }
    )

    assert profile["categories"] == ["Music", "Pop"]
    assert profile["tags"] == ["Official"]


def test_instagram_variant_classifier_never_returns_an_upstream_value() -> None:
    assert batch._instagram_variant_url({"code": "image-code", "media_type": 1}) == (
        "image",
        "https://www.instagram.com/p/image-code/",
    )
    assert batch._instagram_variant_url({"code": "carousel-code", "media_type": 8}) == (
        "carousel",
        "https://www.instagram.com/p/carousel-code/",
    )
    assert batch._instagram_variant_url({"code": "reel-code", "product_type": "clips"}) == (
        "reel",
        "https://www.instagram.com/reel/reel-code/",
    )
    assert batch._instagram_variant_url({"media_type": 1}) is None


def test_failed_refresh_preserves_the_last_successful_capture() -> None:
    merged = batch._merge_report_rows(
        [{"service_id": "instagram.profile", "outcome": "success", "ui_fixture": {"kind": "profile"}}],
        [{"service_id": "instagram.profile", "outcome": "provider_error"}],
    )
    assert merged == [{"service_id": "instagram.profile", "outcome": "success", "ui_fixture": {"kind": "profile"}}]
