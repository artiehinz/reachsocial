"""Run the bounded, paid ScrapeCreators social discovery batch safely.

The report intentionally records only route-level evidence: status, credit
usage, response shape, and item presence.  It never writes a raw upstream
payload, credential, media URL, account identifier, or provider request ID.
Successful discovery samples are *not* publication approval; a route still
needs a ReachSocial service contract, normalizer, fixture, cost review, and
explicit release decision before it may be enabled.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from reachsocial.config import get_settings

Case = tuple[str, str, dict[str, str], tuple[str, ...]]
_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
_MEDIA_FIELD_TOKENS = (
    "video",
    "image",
    "thumbnail",
    "cover",
    "display",
    "media",
    "avatar",
    "profile_pic",
    "play",
    "download",
)
_MEDIA_MAX_BYTES = 30 * 1024 * 1024


CASES: tuple[Case, ...] = (
    ("instagram.profile", "/v1/instagram/profile", {"handle": "instagram"}, ("data",)),
    ("instagram.profile_posts", "/v2/instagram/user/posts", {"handle": "instagram"}, ("items",)),
    ("instagram.search", "/v1/instagram/search", {"query": "nike"}, ("users",)),
    ("x.profile", "/v1/twitter/profile", {"handle": "Austen"}, ()),
    ("x.post", "/v1/twitter/tweet", {"url": "https://x.com/Austen/status/1628769691547074562"}, ()),
    ("x.user_tweets", "/v1/twitter/user-tweets", {"handle": "Austen"}, ("tweets",)),
    ("tiktok.profile", "/v1/tiktok/profile", {"handle": "charlidamelio"}, ()),
    (
        "tiktok.video",
        "/v2/tiktok/video",
        {"url": "https://www.tiktok.com/@stoolpresidente/video/7463250363559218474"},
        ("aweme_detail",),
    ),
    ("tiktok.feed", "/v3/tiktok/profile/videos", {"handle": "charlidamelio", "max_cursor": "0", "sort_by": "latest"}, ("aweme_list",)),
    ("tiktok.user_search", "/v1/tiktok/search/users", {"query": "charli"}, ()),
    ("youtube.channel", "/v1/youtube/channel", {"handle": "ThePatMcAfeeShow"}, ("channel",)),
    ("youtube.video", "/v1/youtube/video", {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}, ()),
    ("youtube.channel_videos", "/v1/youtube/channel-videos", {"handle": "ThePatMcAfeeShow", "sort": "latest", "includeExtras": "true"}, ("videos",)),
    ("youtube.search", "/v1/youtube/search", {"query": "OpenAI", "type": "videos", "sortBy": "relevance", "includeExtras": "true"}, ("videos",)),
)

# These are deliberately opt-in capture follow-ups, not additions to the
# product-validation batch.  They let the offline lab show a saved destination
# for a concrete search result without silently spending a paid provider call.
FOLLOW_UP_CASES: tuple[Case, ...] = (
    ("instagram.nikefootball_profile", "/v1/instagram/profile", {"handle": "nikefootball"}, ("data",)),
    ("instagram.nikefootball_search", "/v1/instagram/search", {"query": "nikefootball"}, ("users",)),
    ("tiktok.stoolpresidente_profile", "/v1/tiktok/profile", {"handle": "stoolpresidente"}, ()),
    ("youtube.rickastley_channel", "/v1/youtube/channel", {"handle": "RickAstleyYT"}, ("channel",)),
)


def _shape(payload: Any, expected_keys: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"json_object": False, "expected_keys_present": False, "top_level_keys": []}
    visible = sorted(str(key) for key in payload if str(key) not in {"data"})[:16]
    expected = all(key in payload for key in expected_keys)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    list_counts = {
        key: len(value)
        for key, value in {**payload, **data}.items()
        if isinstance(value, list) and key in {"items", "tweets", "videos", "profiles", "users", "aweme_list"}
    }
    return {
        "json_object": True,
        "expected_keys_present": expected,
        "top_level_keys": visible,
        "list_counts": list_counts,
        "has_cursor": any(key in payload or key in data for key in ("cursor", "max_cursor", "continuationToken")),
    }


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _first(source: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        value: Any = source
        for part in path.split("."):
            if isinstance(value, dict):
                value = value.get(part)
            elif isinstance(value, list) and part.isdigit():
                index = int(part)
                value = value[index] if index < len(value) else None
            else:
                value = None
                break
        if value not in (None, "", [], {}):
            return value
    return None


def _deep_first(source: Any, *keys: str) -> Any:
    """Find an allowlisted field through provider wrapper objects, never by value."""
    wanted = set(keys)
    queue: list[Any] = [source]
    while queue:
        value = queue.pop(0)
        if isinstance(value, dict):
            for key, nested in value.items():
                if key in wanted and nested not in (None, "", [], {}):
                    return nested
                if isinstance(nested, (dict, list)):
                    queue.append(nested)
        elif isinstance(value, list):
            queue.extend(value[:8])
    return None


def _first_or_deep(source: dict[str, Any], *paths: str) -> Any:
    return _first(source, *paths) or _deep_first(source, *(path.rsplit(".", 1)[-1] for path in paths))


def _safe_text(value: Any, *, limit: int = 280) -> str | None:
    """Keep small public presentation text; remove links and provider tokens."""
    if not isinstance(value, (str, int, float)):
        return None
    text = _URL_PATTERN.sub("[link]", str(value)).replace("\x00", " ").strip()
    return text[:limit] or None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _safe_count(value: Any) -> int | None:
    """Parse provider counts while tolerating compact public display strings."""
    direct = _safe_int(value)
    if direct is not None:
        return direct
    if not isinstance(value, str):
        return None
    match = re.search(r"([\d,.]+)\s*([KMB])?", value.strip(), re.IGNORECASE)
    if not match:
        return None
    try:
        number = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(
        (match.group(2) or "").upper(), 1
    )
    return int(number * multiplier)


def _safe_text_list(value: Any, *, limit: int = 8) -> list[str]:
    values = value if isinstance(value, list) else [value]
    result: list[str] = []
    for item in values:
        pieces = item.split(",") if isinstance(item, str) else [item]
        for piece in pieces:
            text = _safe_text(piece, limit=80)
            if not text or text.isdigit() or any(text.casefold() == existing.casefold() for existing in result):
                continue
            result.append(text)
            if len(result) >= limit:
                return result
    return result


def _result_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = _mapping(payload.get("data"))
    return data or payload


def _ui_profile(source: dict[str, Any]) -> dict[str, Any]:
    user = _mapping(source.get("user"))
    source = {**source, **user} if user else source
    categories = _safe_text_list(
        _first_or_deep(
            source,
            "category",
            "category_name",
            "business_category_name",
            "account_type",
            "keywords",
        )
    )
    tags = _safe_text_list(
        _first_or_deep(source, "tags", "labels", "hashtags", "interests")
    )
    return {
        "display_name": _safe_text(_first_or_deep(source, "full_name", "fullName", "displayName", "name", "nickname", "user.nickname", "channelTitle"), limit=100),
        "handle": _safe_text(_first_or_deep(source, "username", "userName", "handle", "uniqueId", "unique_id", "screen_name", "user.uniqueId", "channelHandle", "channelTitle"), limit=100),
        "biography": _safe_text(_first_or_deep(source, "biography", "bio", "description", "signature", "user.signature")),
        "verified": bool(_first_or_deep(source, "is_verified", "verified", "isVerified", "user.verified")),
        "categories": categories,
        "tags": [tag for tag in tags if not any(tag.casefold() == category.casefold() for category in categories)],
        "counts": {
            "followers": _safe_int(_first(source, "edge_followed_by.count", "follower_count", "followers", "followersCount", "followerCount", "stats.followerCount", "legacy.followers_count", "subscriberCount")),
            "following": _safe_int(_first(source, "edge_follow.count", "following_count", "following", "followingCount", "stats.followingCount", "legacy.friends_count")),
            "content": _safe_int(_first(source, "edge_owner_to_timeline_media.count", "media_count", "posts_count", "videoCount", "stats.videoCount", "legacy.statuses_count")),
        },
    }


def _ui_post(source: dict[str, Any]) -> dict[str, Any]:
    tweet_result = _mapping(_mapping(source.get("tweet_results")).get("result"))
    source = (
        tweet_result
        or _mapping(source.get("aweme_detail"))
        or _mapping(source.get("aweme_info"))
        or source
    )
    author = (
        _mapping(source.get("owner"))
        or _mapping(source.get("author"))
        or _mapping(source.get("user"))
        or _mapping(_first(source, "core.user_results.result"))
        or _mapping(source.get("channel"))
    )
    media_rows = _rows(_first_or_deep(source, "carousel_media", "carouselMedia", "images", "media") or [])
    return {
        "type": _safe_text(_first_or_deep(source, "product_type", "type", "contentType", "media_type"), limit=40),
        "caption": _safe_text(_first_or_deep(source, "caption", "text", "desc", "description", "title", "full_text", "legacy.full_text")),
        "author": _ui_profile(author) if author else {},
        "metrics": {
            "likes": _safe_count(_first_or_deep(source, "likes_count", "likesCount", "likeCount", "like_count", "likeCountText", "diggCount", "digg_count", "statistics.diggCount", "statistics.digg_count", "stats.diggCount", "stats.digg_count", "favorite_count", "legacy.favorite_count")),
            "comments": _safe_count(_first_or_deep(source, "comments_count", "commentsCount", "commentCount", "comment_count", "commentCountText", "statistics.commentCount", "statistics.comment_count", "stats.commentCount", "stats.comment_count", "reply_count", "legacy.reply_count")),
            "shares": _safe_count(_first_or_deep(source, "shares_count", "sharesCount", "shareCount", "share_count", "statistics.shareCount", "retweet_count", "legacy.retweet_count")),
            "views": _safe_count(_first_or_deep(source, "video_view_count", "videoViewCount", "viewCount", "viewCountText", "shortViewCountText", "playCount", "play_count", "statistics.playCount", "statistics.play_count", "stats.playCount", "stats.play_count", "views.count", "views")),
            "bookmarks": _safe_count(_first_or_deep(source, "bookmarkCount", "bookmark_count", "collectCount", "collect_count", "statistics.collectCount", "stats.collectCount", "legacy.bookmark_count")),
            "quotes": _safe_count(_first_or_deep(source, "quoteCount", "quote_count", "legacy.quote_count")),
        },
        "media": {
            "has_media": bool(_first_or_deep(source, "display_url", "displayUrl", "video_url", "videoUrl", "video", "image", "thumbnail", "cover", "thumbnailUrl")),
            "item_count": len(media_rows) or 1,
        },
    }


def _ui_fixture(service_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Project one raw response into a compact UI fixture with no IDs or URLs."""
    data = _result_data(payload)
    if service_id in {"instagram.profile", "instagram.nikefootball_profile", "x.profile", "tiktok.profile", "tiktok.stoolpresidente_profile", "youtube.channel", "youtube.rickastley_channel"}:
        source = _mapping(data.get("channel")) or data
        return {"kind": "profile", "profile": _ui_profile(source)}
    if service_id in {"instagram.profile_posts", "x.user_tweets", "tiktok.feed", "youtube.channel_videos"}:
        rows = _rows(_first(data, "items", "tweets", "aweme_list", "videos") or [])
        return {"kind": "feed", "items": [_ui_post(row) for row in rows[:3]], "item_count": len(rows)}
    if service_id in {"instagram.search", "instagram.nikefootball_search", "tiktok.user_search"}:
        rows = _rows(_first(data, "users", "items", "videos", "channels") or [])
        return {"kind": "search", "items": [_ui_profile(row) for row in rows[:3]], "item_count": len(rows)}
    if service_id == "youtube.search":
        rows = _rows(_first(data, "videos", "shorts", "channels") or [])
        return {"kind": "search", "items": [_ui_post(row) for row in rows[:3]], "item_count": len(rows)}
    if service_id == "tiktok.video":
        return {"kind": "post", "item": _ui_post(_mapping(data.get("aweme_detail")) or data)}
    if service_id in {"instagram.image", "instagram.carousel", "instagram.reel"}:
        item = _mapping(data.get("xdt_shortcode_media")) or _mapping(data.get("shortcode_media")) or data
        return {"kind": "post", "item": _ui_post(item)}
    return {"kind": "post", "item": _ui_post(data)}


def _media_candidates(value: Any, parent_key: str = "") -> list[tuple[str, str]]:
    """Find direct media candidates in memory without retaining their URLs."""
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            key_name = str(key).lower()
            context = key_name if any(token in key_name for token in _MEDIA_FIELD_TOKENS) else parent_key
            found.extend(_media_candidates(nested, context))
    elif isinstance(value, list):
        for nested in value[:12]:
            found.extend(_media_candidates(nested, parent_key))
    elif isinstance(value, str) and value.startswith(("https://", "http://")):
        if any(token in parent_key for token in _MEDIA_FIELD_TOKENS):
            found.append((value, parent_key))
    deduped = {url: context for url, context in found}
    return sorted(deduped.items(), key=lambda item: item[0])


def _media_candidate_priority(context: str, *, prefer_video: bool) -> int:
    is_video = any(token in context for token in ("video", "play_addr", "download"))
    return 0 if is_video == prefer_video else 1


def _is_video_media_candidate(context: str) -> bool:
    return any(token in context for token in ("video", "play_addr", "download"))


def _selected_media_candidates(
    service_id: str,
    candidates: list[tuple[str, str]],
    *,
    prefer_video: bool = False,
) -> list[tuple[str, str]]:
    """Keep only the assets needed for an honest compact lab preview."""
    if prefer_video:
        videos = [item for item in candidates if _is_video_media_candidate(item[1])]
        posters = [item for item in candidates if not _is_video_media_candidate(item[1])]
        return videos[:3] + posters[:3]
    if service_id == "instagram.carousel":
        return candidates[:6]
    if service_id.startswith(("instagram.profile", "instagram.search")) or service_id in {"x.profile", "tiktok.profile", "tiktok.stoolpresidente_profile", "youtube.channel", "youtube.rickastley_channel"}:
        return sorted(candidates, key=lambda item: (0 if any(token in item[1] for token in ("profile", "avatar")) else 1, item[0]))[:1]
    return candidates[:1]


def _raw_post_author(source: dict[str, Any]) -> dict[str, Any]:
    tweet_result = _mapping(_mapping(source.get("tweet_results")).get("result"))
    source = (
        tweet_result
        or _mapping(source.get("aweme_detail"))
        or _mapping(source.get("aweme_info"))
        or source
    )
    return (
        _mapping(source.get("owner"))
        or _mapping(source.get("author"))
        or _mapping(source.get("user"))
        or _mapping(_first(source, "core.user_results.result"))
        or _mapping(source.get("channel"))
    )


def _raw_rows_for_fixture(service_id: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = _result_data(payload)
    if service_id in {"instagram.profile", "instagram.nikefootball_profile", "x.profile", "tiktok.profile", "tiktok.stoolpresidente_profile", "youtube.channel", "youtube.rickastley_channel"}:
        return [_mapping(data.get("channel")) or data]
    if service_id in {"instagram.profile_posts", "x.user_tweets", "tiktok.feed", "youtube.channel_videos", "youtube.search"}:
        return _rows(_first(data, "items", "tweets", "aweme_list", "videos", "shorts") or [])
    if service_id == "tiktok.video":
        return [_mapping(data.get("aweme_detail")) or data]
    if service_id in {"instagram.search", "instagram.nikefootball_search", "tiktok.user_search"}:
        return _rows(_first(data, "users", "items", "videos", "channels") or [])
    if service_id in {"instagram.image", "instagram.carousel", "instagram.reel"}:
        return [_mapping(data.get("xdt_shortcode_media")) or _mapping(data.get("shortcode_media")) or data]
    return [data]


async def _download_media_asset(
    client: httpx.AsyncClient, source_url: str, destination: Path
) -> tuple[str, str] | None:
    """Save one bounded image/video locally, returning only its local filename."""
    try:
        async with client.stream("GET", source_url, follow_redirects=True, headers={"Accept": "image/*,video/*"}) as response:
            if response.status_code != 200:
                return None
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            suffix_hint = Path(urlparse(source_url).path).suffix.lower()
            if content_type == "application/octet-stream" and suffix_hint in {".mp4", ".mov", ".webm"}:
                content_type = "video/mp4" if suffix_hint == ".mp4" else f"video/{suffix_hint[1:]}"
            if not content_type.startswith(("image/", "video/")) or content_type == "image/heic":
                return None
            expected_size = int(response.headers.get("content-length") or 0)
            if expected_size > _MEDIA_MAX_BYTES:
                return None
            suffix = mimetypes.guess_extension(content_type) or (".mp4" if content_type.startswith("video/") else ".jpg")
            destination = destination.with_suffix(suffix)
            total = 0
            with destination.open("wb") as handle:
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > _MEDIA_MAX_BYTES:
                        handle.close()
                        destination.unlink(missing_ok=True)
                        return None
                    handle.write(chunk)
    except (httpx.HTTPError, OSError, ValueError):
        return None
    return destination.name, ("video" if content_type.startswith("video/") else "image")


async def _attach_media_assets(
    client: httpx.AsyncClient,
    service_id: str,
    payload: dict[str, Any],
    fixture: dict[str, Any],
    media_dir: Path,
) -> None:
    """Attach locally stored media names to compact fixture rows, never URLs."""
    raw_rows = _raw_rows_for_fixture(service_id, payload)
    fixture_kind = str(fixture.get("kind") or "")
    target_rows: list[dict[str, Any]]
    if fixture_kind == "profile":
        target_rows = [_mapping(fixture.get("profile"))]
    elif fixture_kind in {"feed", "search"}:
        target_rows = _rows(fixture.get("items"))
    else:
        target_rows = [_mapping(fixture.get("item"))]
    media_dir.mkdir(parents=True, exist_ok=True)
    for index, (raw_row, target_row) in enumerate(
        zip(raw_rows[:3], target_rows[:3], strict=False), 1
    ):
        candidates = _media_candidates(raw_row)
        declared_type = str(target_row.get("type") or "").casefold()
        prefer_video = service_id in {"tiktok.video", "tiktok.feed", "instagram.reel", "youtube.video", "youtube.channel_videos", "youtube.search"} or declared_type in {
            "clips",
            "reel",
            "reels",
            "video",
        }
        candidates.sort(
            key=lambda item: (
                _media_candidate_priority(item[1], prefer_video=prefer_video),
                item[0],
            )
        )
        candidates = _selected_media_candidates(
            service_id,
            candidates,
            prefer_video=prefer_video,
        )
        assets: list[dict[str, str]] = []
        captured_types: set[str] = set()
        for asset_index, (candidate, _context) in enumerate(candidates, 1):
            expected_type = "video" if _is_video_media_candidate(_context) else "image"
            if expected_type in captured_types:
                continue
            asset = await _download_media_asset(client, candidate, media_dir / f"{service_id.replace('.', '-')}-{index}-{asset_index}")
            if asset:
                name, asset_type = asset
                if asset_type in captured_types:
                    (media_dir / name).unlink(missing_ok=True)
                    continue
                assets.append({"name": name, "type": asset_type})
                captured_types.add(asset_type)
                if not prefer_video or captured_types == {"video", "image"}:
                    break
        if assets:
            target_row["media_asset"] = assets[0]["name"]
            target_row["media_asset_type"] = assets[0]["type"]
            target_row["media_assets"] = assets
            thumbnail = next((asset for asset in assets if asset["type"] == "image"), None)
            if thumbnail is not None:
                target_row["media_thumbnail_asset"] = thumbnail["name"]
        if fixture_kind in {"feed", "post"} or service_id == "youtube.search":
            raw_author = _raw_post_author(raw_row)
            target_author = _mapping(target_row.get("author"))
            author_candidates = sorted(
                _media_candidates(raw_author),
                key=lambda item: (
                    0 if any(token in item[1] for token in ("profile", "avatar", "thumbnail")) else 1,
                    item[0],
                ),
            )
            if target_author:
                for author_candidate, _context in author_candidates[:3]:
                    author_asset = await _download_media_asset(
                        client,
                        author_candidate,
                        media_dir / f"{service_id.replace('.', '-')}-{index}-author",
                    )
                    if author_asset:
                        target_author["media_asset"] = author_asset[0]
                        break


async def _run_case(
    client: httpx.AsyncClient, case: Case, api_key: str, *, media_dir: Path | None = None
) -> dict[str, Any]:
    service_id, route, params, expected_keys = case
    try:
        response = await client.get(route, params=params, headers={"x-api-key": api_key})
    except httpx.TimeoutException:
        return {"service_id": service_id, "outcome": "timeout", "credits_charged": 0}
    except httpx.HTTPError:
        return {"service_id": service_id, "outcome": "connection_error", "credits_charged": 0}
    try:
        payload = response.json()
    except ValueError:
        payload = None
    credits = payload.get("credits_charged", 0) if isinstance(payload, dict) else 0
    try:
        credits = max(0, int(credits or 0))
    except (TypeError, ValueError):
        credits = 0
    result = {
        "service_id": service_id,
        "outcome": "success" if response.status_code == 200 and isinstance(payload, dict) and payload.get("success") is not False else "provider_error",
        "http_status": response.status_code,
        "credits_charged": credits,
        "shape": _shape(payload, expected_keys),
    }
    if result["outcome"] == "success" and isinstance(payload, dict):
        fixture = _ui_fixture(service_id, payload)
        if media_dir is not None:
            await _attach_media_assets(client, service_id, payload, fixture, media_dir)
        result["ui_fixture"] = fixture
    return result


def _instagram_variant_url(row: dict[str, Any]) -> tuple[str, str] | None:
    """Classify an in-memory Instagram grid item without retaining it."""
    code = str(row.get("code") or row.get("shortcode") or "").strip()
    if not code:
        return None
    product_type = str(row.get("product_type") or "").strip().lower()
    media_type = str(row.get("media_type") or "").strip()
    is_carousel = bool(row.get("carousel_media")) or media_type == "8" or "carousel" in product_type
    is_video = media_type == "2" or product_type in {"clips", "reel", "reels"}
    if is_carousel:
        return "carousel", f"https://www.instagram.com/p/{code}/"
    if is_video:
        return "reel", f"https://www.instagram.com/reel/{code}/"
    if media_type == "1" or product_type in {"feed", ""}:
        return "image", f"https://www.instagram.com/p/{code}/"
    return None


async def _run_instagram_variants(
    client: httpx.AsyncClient,
    api_key: str,
    *,
    handle: str = "instagram",
    media_dir: Path | None = None,
    kinds: tuple[str, ...] = ("image", "carousel", "reel"),
) -> list[dict[str, Any]]:
    """Validate image, carousel, and reel detail routes from a public feed.

    Provider rows exist only in this coroutine.  The resulting report has the
    same sanitized shape as the rest of the batch and never contains a URL,
    handle, caption, media URL, or post identifier.
    """
    try:
        response = await client.get(
            "/v2/instagram/user/posts",
            params={"handle": handle},
            headers={"x-api-key": api_key},
        )
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return [{"service_id": "instagram.variants", "outcome": "discovery_error", "credits_charged": 0}]
    if not isinstance(payload, dict):
        return [{"service_id": "instagram.variants", "outcome": "invalid_response", "credits_charged": 0}]
    discovery = {
        "service_id": "instagram.variant_discovery",
        "outcome": "success" if response.status_code == 200 and payload.get("success") is not False else "provider_error",
        "http_status": response.status_code,
        "credits_charged": max(0, int(payload.get("credits_charged") or 0)),
        "shape": _shape(payload, ("items",)),
    }
    if discovery["outcome"] != "success":
        return [discovery]
    rows = payload.get("items")
    selected: dict[str, str] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        candidate = _instagram_variant_url(row)
        if candidate and candidate[0] not in selected:
            selected[candidate[0]] = candidate[1]
    results = [discovery]
    for kind in kinds:
        url = selected.get(kind)
        if not url:
            results.append({"service_id": f"instagram.{kind}", "outcome": "not_present_in_sample", "credits_charged": 0})
            continue
        result = await _run_case(
            client,
            (f"instagram.{kind}", "/v1/instagram/post", {"url": url, "download_media": "false"}, ("data",)),
            api_key,
            media_dir=media_dir,
        )
        results.append(result)
    return results


async def run(
    output: Path,
    *,
    include_instagram_variants: bool = False,
    include_base_cases: bool = True,
    instagram_handle: str = "instagram",
    cases: tuple[Case, ...] = CASES,
    media_dir: Path | None = None,
    instagram_variant_kinds: tuple[str, ...] = ("image", "carousel", "reel"),
    download_tiktok_media: bool = False,
    x_post_url: str | None = None,
) -> dict[str, Any]:
    api_key = get_settings().scrapecreators_api_key
    if not api_key:
        raise SystemExit("SCRAPECREATORS_API_KEY is not configured")
    effective_cases: list[Case] = []
    for service_id, route, params, expected_keys in cases:
        adjusted = dict(params)
        if service_id == "tiktok.video" and download_tiktok_media:
            adjusted["download_media"] = "true"
        if service_id == "x.post" and x_post_url:
            adjusted["url"] = x_post_url
        effective_cases.append((service_id, route, adjusted, expected_keys))
    async with httpx.AsyncClient(base_url="https://api.scrapecreators.com", timeout=35.0) as client:
        results = [await _run_case(client, case, api_key, media_dir=media_dir) for case in effective_cases] if include_base_cases else []
        if include_instagram_variants:
            results.extend(await _run_instagram_variants(client, api_key, handle=instagram_handle, media_dir=media_dir, kinds=instagram_variant_kinds))
    report = {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "purpose": "bounded product-discovery validation; no route is accepted or enabled by this report",
        "case_count": len(results),
        "credits_charged_total": sum(int(row.get("credits_charged") or 0) for row in results),
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _merge_report_rows(existing_results: Any, refreshed_results: Any) -> list[dict[str, Any]]:
    """Keep a usable capture when a narrow paid refresh fails."""
    existing_rows = {
        str(row.get("service_id")): row
        for row in existing_results
        if isinstance(row, dict)
    }
    for refreshed_row in refreshed_results:
        if not isinstance(refreshed_row, dict):
            continue
        service_id = str(refreshed_row.get("service_id"))
        previous_row = existing_rows.get(service_id)
        if (
            refreshed_row.get("outcome") != "success"
            and isinstance(previous_row, dict)
            and previous_row.get("outcome") == "success"
        ):
            continue
        existing_rows[service_id] = refreshed_row
    return list(existing_rows.values())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/generated/scrapecreators-social-batch.json"))
    parser.add_argument("--include-instagram-variants", action="store_true")
    parser.add_argument("--variants-only", action="store_true")
    parser.add_argument("--instagram-handle", default="instagram")
    parser.add_argument("--case", action="append", choices=[case[0] for case in (*CASES, *FOLLOW_UP_CASES)], help="Run only a named bounded capture case; may be specified more than once.")
    parser.add_argument("--media-dir", type=Path, help="Optional local directory for bounded image/video assets used by the UI lab.")
    parser.add_argument("--variant-kind", action="append", choices=("image", "carousel", "reel"), help="Run only selected Instagram variant detail calls.")
    parser.add_argument("--download-tiktok-media", action="store_true", help="Request the provider's paid permanent TikTok media URL for the selected TikTok video case.")
    parser.add_argument("--x-post-url", help="Use one explicit canonical X post URL for the selected x.post capture.")
    parser.add_argument("--merge-existing", action="store_true", help="Replace matching service rows in an existing output file after a narrow refresh.")
    parser.add_argument("--confirm-paid-provider-calls", action="store_true")
    args = parser.parse_args()
    if not args.confirm_paid_provider_calls:
        raise SystemExit("Re-run with --confirm-paid-provider-calls to acknowledge provider cost")
    if args.variants_only and not args.include_instagram_variants:
        parser.error("--variants-only requires --include-instagram-variants")
    all_cases = (*CASES, *FOLLOW_UP_CASES)
    selected_cases = CASES if not args.case else tuple(case for case in all_cases if case[0] in set(args.case))
    existing_report: dict[str, Any] | None = None
    if args.merge_existing and args.output.exists():
        try:
            loaded = json.loads(args.output.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing_report = loaded
        except (OSError, ValueError):
            raise SystemExit(
                "unable to read the existing sanitized fixture output"
            ) from None
    report = asyncio.run(
        run(
            args.output,
            include_instagram_variants=args.include_instagram_variants,
            include_base_cases=not args.variants_only,
            instagram_handle=args.instagram_handle,
            cases=selected_cases,
            media_dir=args.media_dir,
            instagram_variant_kinds=tuple(args.variant_kind or ("image", "carousel", "reel")),
            download_tiktok_media=args.download_tiktok_media,
            x_post_url=args.x_post_url,
        )
    )
    if existing_report is not None:
        try:
            report["results"] = _merge_report_rows(existing_report.get("results", []), report["results"])
            report["case_count"] = len(report["results"])
            report["credits_charged_total"] = sum(int(row.get("credits_charged") or 0) for row in report["results"])
            args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except (OSError, ValueError, TypeError):
            raise SystemExit(
                "unable to merge the existing sanitized fixture output"
            ) from None
    print(f"cases={report['case_count']}")
    print(f"credits_charged_total={report['credits_charged_total']}")
    for row in report["results"]:
        print(f"{row['service_id']}={row['outcome']}")


if __name__ == "__main__":
    main()
