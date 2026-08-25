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
