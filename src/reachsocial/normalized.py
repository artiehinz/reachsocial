from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Iterable
from urllib.parse import urlparse


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _first(source: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        value: Any = source
        for part in path.split("."):
            if isinstance(value, list) and part.isdigit():
                index = int(part)
                value = value[index] if index < len(value) else None
            elif isinstance(value, dict) and part in value:
                value = value[part]
            else:
                value = None
                break
        if value not in (None, "", [], {}):
            return value
    return None


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    text = str(value).strip()
    return text or None


def _text_values(value: Any, *, limit: int = 12) -> list[str]:
    values = value if isinstance(value, list) else [value]
    output: list[str] = []
    for item in values:
        text = _text(item.get("name") if isinstance(item, dict) else item)
        if text and text not in output:
            output.append(text)
        if len(output) >= limit:
            break
    return output


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
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


def _boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    return None


def _timestamp(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
        integer_value = int(value)
        if 1900 <= integer_value <= 2100 and len(str(value)) == 4:
            return f"{integer_value:04d}-01-01T00:00:00Z"
        try:
            return datetime.fromtimestamp(integer_value, tz=UTC).isoformat().replace("+00:00", "Z")
        except (ValueError, OSError, OverflowError):
            return None
    if isinstance(value, float):
        try:
            return datetime.fromtimestamp(value, tz=UTC).isoformat().replace("+00:00", "Z")
        except (ValueError, OSError, OverflowError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%a %b %d %H:%M:%S %z %Y")
            return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
        except ValueError:
            return text


def _handle_from_url(url: str) -> str | None:
    parts = [part for part in urlparse(url).path.split("/") if part]
    if not parts:
        return None
    youtube = (urlparse(url).hostname or "").lower() in {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
    }
    if youtube and parts[0] == "channel":
        return None
    if (parts[0] in {"in", "pub"} or youtube and parts[0] in {"c", "user"}) and len(parts) > 1:
        return parts[1]
    return parts[0].removeprefix("@")


def _url(value: Any) -> str | None:
    text = _text(value)
    if text and text.startswith(("https://", "http://")):
        return text
    return None


def _first_url(source: dict[str, Any], *paths: str) -> str | None:
    # A nonempty mapping is not a URL and must not mask later valid variants.
    return next((url for path in paths if (url := _url(_first(source, path)))), None)


def _first_browser_image_url(source: dict[str, Any], *paths: str) -> str | None:
    # TikTok puts HEIC .image variants before separately signed JPEG URLs.
    # Select a supplied compatible variant; never rewrite a signed URL.
    candidates: list[str] = []
    for path in paths:
        value = _first(source, path)
        if isinstance(value, dict):
            value = _first(value, "url_list", "urlList", "url")
        for candidate in value if isinstance(value, list) else [value]:
            if url := _url(candidate):
                candidates.append(url)
    return next(
        (
            url
            for url in candidates
            if urlparse(url)
            .path.lower()
            .endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"))
        ),
        candidates[0] if candidates else None,
    )


def _media(
    *,
    media_type: str,
    source_url: Any,
    preview_url: Any = None,
    width: Any = None,
    height: Any = None,
    duration: Any = None,
    expires_at: Any = None,
) -> dict[str, Any] | None:
    source = _url(source_url)
    preview = _url(preview_url)
    if not source and not preview:
        return None
    return {
        "type": media_type,
        "url": source,
        "preview_url": preview,
        "width": _integer(width),
        "height": _integer(height),
        "duration_seconds": _integer(duration),
        "expires_at": _timestamp(expires_at),
    }


def _dedupe_media(values: Iterable[dict[str, Any] | None]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any]] = set()
    for value in values:
        if value is None:
            continue
        key = (value.get("url"), value.get("preview_url"))
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output


def _profile(
    platform: str,
    canonical_url: str,
    source: dict[str, Any],
    *,
    service_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    legacy = _mapping(source.get("legacy"))
    user = _mapping(source.get("user"))
    normalized_source = {**source, **user} if user else source
    handle = _first(
        normalized_source,
        "username",
        "userName",
        "handle",
        "uniqueId",
        "unique_id",
        "screen_name",
        "user.uniqueId",
        "legacy.screen_name",
        "publicIdentifier",
        "channelHandle",
    ) or _handle_from_url(canonical_url)
    display_name = _first(
        normalized_source,
        "full_name",
        "fullName",
        "displayName",
        "name",
        "nickname",
        "channelTitle",
        "title",
        "user.nickname",
        "legacy.name",
    )
    biography = _first(
        normalized_source,
        "biography",
        "bio",
        "about",
        "summary",
        "signature",
        "user.signature",
        "legacy.description",
        "headline",
        "description",
    )
    avatar = _first_url(
        normalized_source,
        "profile_pic_url_hd",
        "profile_pic_url",
        "profilePicture",
        "profilePictureUrl",
        "profileImageUrl",
        "image",
        "avatar.url",
        "avatar.image.sources.0.url",
        "avatar.thumbnails.0.url",
        "thumbnail",
        "thumbnails.0.url",
        "avatarLarger",
        "avatarMedium",
        "avatar_larger.url_list.0",
        "avatar_medium.url_list.0",
        "avatar_thumb.url_list.0",
        "user.avatarLarger",
        "user.avatarMedium",
        "legacy.profile_image_url_https",
    )
    external = _first(
        normalized_source,
        "external_url",
        "website",
        "bioLink.link",
        "user.bioLink.link",
        "legacy.entities.url.urls.0.expanded_url",
    )
    categories = _text_values(
        _first(
            normalized_source,
            "categories",
            "category",
            "category_name",
            "business_category_name",
            "account_type",
        )
    )
    tags = _text_values(_first(normalized_source, "tags", "labels", "interests", "keywords"))
    fields = {
        **({"categories": categories} if categories else {}),
        **({"tags": tags} if tags else {}),
        **(service_fields or {}),
    }
    result = {
        "platform": platform,
        "canonical_url": canonical_url,
        "platform_id": _text(
            _first(
                normalized_source,
                "rest_id" if platform == "X" else "id",
                "id" if platform == "X" else "rest_id",
                "uid",
                "user.id",
                "secUid",
                "user.secUid",
                "urn",
                "channelId",
            )
        ),
        "handle": (_text(handle) or "").removeprefix("@") or None,
        "display_name": _text(display_name),
        "biography": _text(biography),
        "avatar_url": _url(avatar),
        "verified": _boolean(
            _first(
                normalized_source,
                "is_verified",
                "verified",
                "isVerified",
                "is_blue_verified",
                "user.verified",
            )
        ),
        "private": _boolean(
            _first(
                normalized_source,
                "is_private",
                "privateAccount",
                "user.privateAccount",
                "legacy.protected",
            )
        ),
        "counts": {
            "followers": _integer(
                _first(
                    normalized_source,
                    "follower_count",
                    "followers",
                    "followersCount",
                    "followerCount",
                    "stats.followerCount",
                    "edge_followed_by.count",
                    "legacy.followers_count",
                    "subscriberCount",
                    "subscriberCountText",
                )
            ),
            "following": _integer(
                _first(
                    normalized_source,
                    "following_count",
                    "following",
                    "followingCount",
                    "stats.followingCount",
                    "edge_follow.count",
                    "legacy.friends_count",
                )
            ),
            "content": _integer(
                _first(
                    normalized_source,
                    "media_count",
                    "posts_count",
                    "videoCount",
                    "stats.videoCount",
                    "edge_owner_to_timeline_media.count",
                    "legacy.statuses_count",
                    "videoCountText",
                )
            ),
        },
        "links": [external] if _url(external) else [],
        "fields": fields,
    }
    del legacy, user
    return result


def _author(
    platform: str, source: dict[str, Any], canonical_url: str | None = None
) -> dict[str, Any]:
    allowed_hosts = {
        "Instagram": {"instagram.com", "www.instagram.com"},
        "X": {"x.com", "www.x.com", "twitter.com", "www.twitter.com"},
        "TikTok": {"tiktok.com", "www.tiktok.com"},
        "YouTube": {"youtube.com", "www.youtube.com"},
        "Facebook": {"facebook.com", "www.facebook.com", "m.facebook.com"},
        "Reddit": {"reddit.com", "www.reddit.com", "old.reddit.com"},
    }
    if canonical_url and (urlparse(canonical_url).hostname or "").lower() not in allowed_hosts.get(
        platform, set()
    ):
        canonical_url = None
    profile = _profile(platform, canonical_url or "", source)
    handle = profile["handle"]
    if handle:
        canonical_url = {
            "Instagram": f"https://www.instagram.com/{handle}/",
            "X": f"https://x.com/{handle}",
            "TikTok": f"https://www.tiktok.com/@{handle}",
            "YouTube": f"https://www.youtube.com/@{handle}",
        }.get(platform, canonical_url)
    elif platform == "YouTube" and profile["platform_id"]:
        canonical_url = f"https://www.youtube.com/channel/{profile['platform_id']}"
    return {
        "platform_id": profile["platform_id"],
        "handle": profile["handle"],
        "display_name": profile["display_name"],
        "avatar_url": profile["avatar_url"],
        "verified": profile["verified"],
        "canonical_url": canonical_url,
    }


def _instagram_media(source: dict[str, Any]) -> list[dict[str, Any]]:
    children = _items(
        _first(
            source,
            "carousel_media",
            "carouselMedia",
            "childPosts",
            "sidecarChildren",
            "edge_sidecar_to_children.edges",
        )
        or []
    )
    candidates: list[dict[str, Any] | None] = []
    for child in children:
        candidates.extend(_instagram_media(_mapping(child.get("node")) or child))
    if children:
        return _dedupe_media(candidates)

    video_url = _first_url(
        source,
        "video_url",
        "videoUrl",
        "video_versions.0.url",
    )
    image_url = _first_url(
        source,
        "display_uri",
        "display_url",
        "displayUrl",
        "image_versions2.candidates.0.url",
        "thumbnail_src",
        "thumbnail",
    )
    candidates.append(
        _media(
            media_type="video" if video_url else "image",
            source_url=video_url or image_url,
            preview_url=image_url if video_url else None,
            width=_first(source, "dimensions.width", "original_width", "width"),
            height=_first(source, "dimensions.height", "original_height", "height"),
            duration=_first(source, "video_duration", "videoDuration"),
        )
    )
    return _dedupe_media(candidates)


def _x_media(source: dict[str, Any]) -> list[dict[str, Any]]:
    legacy = _mapping(source.get("legacy")) or source
    entries = _items(_first(legacy, "extended_entities.media", "entities.media") or [])
    output: list[dict[str, Any] | None] = []
    for value in source.get("media", []) if isinstance(source.get("media"), list) else []:
        if isinstance(value, str):
            output.append(_media(media_type="image", source_url=value))
        elif isinstance(value, dict):
            output.append(
                _media(
                    media_type=_text(_first(value, "type")) or "image",
                    source_url=_first(value, "url", "mediaUrl", "media_url_https"),
                    preview_url=_first(value, "previewUrl", "preview_url"),
                    width=_first(value, "width"),
                    height=_first(value, "height"),
                    duration=_first(value, "duration", "durationSeconds"),
                )
            )
    for entry in entries:
        variants = [
            item
            for item in _items(_first(entry, "video_info.variants") or [])
            if item.get("content_type") == "video/mp4"
            or str(item.get("url") or "").split("?", 1)[0].endswith(".mp4")
        ]
        best_video = max(variants, key=lambda item: _integer(item.get("bitrate")) or 0, default={})
        video_url = _first(best_video, "url")
        duration_millis = _integer(_first(entry, "video_info.duration_millis"))
        output.append(
            _media(
                media_type="video" if entry.get("type") in {"video", "animated_gif"} else "image",
                source_url=(
                    video_url
                    if entry.get("type") in {"video", "animated_gif"}
                    else entry.get("media_url_https") or entry.get("media_url")
                ),
                preview_url=entry.get("media_url_https") or entry.get("media_url"),
                width=_first(entry, "original_info.width", "sizes.large.w"),
                height=_first(entry, "original_info.height", "sizes.large.h"),
                duration=(round(duration_millis / 1000) if duration_millis is not None else None),
            )
        )
    return _dedupe_media(output)


def _tiktok_media(source: dict[str, Any]) -> list[dict[str, Any]]:
    photos = _items(_first(source, "image_post_info.images", "imagePost.images") or [])
    if photos:
        return _dedupe_media(
            _media(
                media_type="image",
                source_url=_first_browser_image_url(photo, "display_image", "imageURL", "url_list"),
                width=_first(photo, "display_image.width", "width"),
                height=_first(photo, "display_image.height", "height"),
            )
            for photo in photos
        )
    video = _mapping(source.get("video"))
    source_url = _first_url(
        source,
        "download_no_watermark_addr.url_list.0",
        "download_no_watermark_addr",
        "play_addr.url_list.0",
        "play_addr",
        "video.download_no_watermark_addr.url_list.0",
        "video.download_addr.url_list.0",
        "video.play_addr.url_list.0",
        "video.downloadAddr.url_list.0",
        "video.downloadAddr.urlList.0",
        "video.downloadAddr",
        "video.playAddr.url_list.0",
        "video.playAddr.urlList.0",
        "video.playAddr",
    )
    preview = _first_browser_image_url(
        source,
        "video.cover",
        "video.originCover",
        "video.origin_cover",
    )
    return _dedupe_media(
        [
            _media(
                media_type="video",
                source_url=source_url,
                preview_url=preview,
                width=_first(video, "width"),
                height=_first(video, "height"),
                duration=_first(video, "duration"),
            )
        ]
    )


def _youtube_media(source: dict[str, Any]) -> list[dict[str, Any]]:
    return _dedupe_media(
        [
            _media(
                media_type="image",
                source_url=_first_url(
                    source,
                    "thumbnailUrl",
                    "thumbnail.url",
                    "thumbnail",
                    "thumbnails.0.url",
                    "videoThumbnails.0.url",
                    "maxresThumbnail",
                    "image",
                ),
                width=_first(source, "thumbnail.width", "thumbnails.0.width"),
                height=_first(source, "thumbnail.height", "thumbnails.0.height"),
            )
        ]
    )


def _content(platform: str, canonical_url: str, source: dict[str, Any]) -> dict[str, Any]:
    legacy = _mapping(source.get("legacy")) or source
    if platform == "Instagram":
        media = _instagram_media(source)
        author_source = _mapping(source.get("owner")) or _mapping(source.get("user"))
    elif platform == "X":
        media = _x_media(source)
        author_source = _mapping(source.get("author")) or _mapping(
            _first(source, "core.user_results.result") or {}
        )
    elif platform == "TikTok":
        media = _tiktok_media(source)
        author_source = _mapping(source.get("author"))
    elif platform == "YouTube":
        media = _youtube_media(source)
        author_source = _mapping(source.get("channel")) or {
            key: source[key]
            for key in ("channelId", "channelHandle", "channelTitle")
            if key in source
        }
    else:
        media = _dedupe_media(
            [
                _media(
                    media_type="image",
                    source_url=_first(source, "image", "imageUrl", "media.url"),
                    preview_url=_first(source, "thumbnail", "thumbnailUrl"),
                )
            ]
        )
        author_source = source
    if platform == "Reddit":
        # Reddit's post ID, name and gallery URL do not identify its author.
        handle = source.get("author")
        author_source = {}
        if isinstance(handle, str) and re.fullmatch(r"[A-Za-z0-9_-]+", handle):
            author_id = source.get("author_fullname")
            author_source = {
                "username": handle,
                "id": author_id
                if isinstance(author_id, str) and re.fullmatch(r"t2_[A-Za-z0-9]+", author_id)
                else None,
                "url": f"https://www.reddit.com/user/{handle}/",
            }
    content_type = _text(_first(source, "type", "product_type", "contentType"))
    has_video = any(item["type"] == "video" for item in media)
    if platform == "Instagram":
        if len(media) > 1 or content_type in {"carousel", "carousel_container", "sidecar"}:
            content_type = "carousel"
        elif has_video or content_type in {"clips", "reel", "reels", "video"}:
            content_type = "video"
        else:
            content_type = "image"
    elif platform == "TikTok":
        content_type = "carousel" if len(media) > 1 else "video" if has_video else "image"
    elif not content_type:
        content_type = "video" if platform == "YouTube" or has_video else "post"
    author = _author(platform, author_source, _url(_first(author_source, "url", "twitterUrl")))
    post_id = _text(
        _first(source, "rest_id", "id", "videoId", "shortcode", "code", "aweme_id", "tweetId")
    )
    if not canonical_url and post_id and author.get("handle"):
        if platform == "X":
            canonical_url = f"https://x.com/{author['handle']}/status/{post_id}"
        elif platform == "TikTok":
            kind = "photo" if content_type in {"image", "carousel"} else "video"
            canonical_url = f"https://www.tiktok.com/@{author['handle']}/{kind}/{post_id}"
    result = {
        "platform": platform,
        "canonical_url": canonical_url
        or _url(_first(source, "url", "permalink", "webVideoUrl", "videoUrl"))
        or (
            f"https://youtube.com/watch?v={_text(_first(source, 'videoId', 'id'))}"
            if platform == "YouTube" and _text(_first(source, "videoId", "id"))
            else None
        ),
        "platform_id": post_id,
        "type": content_type,
        "author": author,
        "text": _text(
            _first(
                source,
                "caption.text",
                "caption",
                "text",
                "desc",
                "description",
                "edge_media_to_caption.edges.0.node.text",
                "legacy.full_text",
                "title",
            )
        ),
        "published_at": _timestamp(
            _first(
                source,
                "timestamp",
                "taken_at",
                "taken_at_timestamp",
                "takenAt",
                "createTime",
                "create_time",
                "create_time_utc",
                "created_at",
                "createdAt",
                "publishedTime",
                "publishedTimeText",
                "legacy.created_at",
            )
        ),
        "expires_at": _timestamp(_first(source, "expires_at", "expiresAt")),
        "media": media,
        "metrics": {
            "likes": _integer(
                _first(
                    source,
                    "like_count",
                    "likes_count",
                    "likesCount",
                    "likeCount",
                    "likeCountText",
                    "edge_media_preview_like.count",
                    "diggCount",
                    "stats.diggCount",
                    "stats.digg_count",
                    "statistics.diggCount",
                    "statistics.digg_count",
                    "legacy.favorite_count",
                    "score",
                    "upvotes",
                )
            ),
            "comments": _integer(
                _first(
                    source,
                    "comments_count",
                    "comment_count",
                    "commentsCount",
                    "commentCount",
                    "commentCountInt",
                    "commentCountText",
                    "edge_media_preview_comment.count",
                    "replyCount",
                    "stats.commentCount",
                    "stats.comment_count",
                    "statistics.commentCount",
                    "statistics.comment_count",
                    "legacy.reply_count",
                    "num_comments",
                )
            ),
            "shares": _integer(
                _first(
                    source,
                    "shares_count",
                    "sharesCount",
                    "shareCount",
                    "retweetCount",
                    "stats.shareCount",
                    "stats.share_count",
                    "statistics.shareCount",
                    "statistics.share_count",
                    "legacy.retweet_count",
                )
            ),
            "views": _integer(
                _first(
                    source,
                    "video_view_count",
                    "video_play_count",
                    "play_count",
                    "ig_play_count",
                    "videoViewCount",
                    "viewCount",
                    "viewCountInt",
                    "viewCountText",
                    "shortViewCountText",
                    "playCount",
                    "stats.playCount",
                    "stats.play_count",
                    "statistics.playCount",
                    "statistics.play_count",
                    "views.count",
                    "views",
                )
            ),
        },
        "relationships": {
            "reply_to_id": _text(_first(legacy, "in_reply_to_status_id_str")),
            "repost_of_id": _text(_first(source, "retweeted_status_result.result.rest_id")),
            "quote_of_id": _text(_first(source, "quoted_status_result.result.rest_id")),
        },
    }

    if platform == "X":
        for key, paths in {
            "quotes": ("quoteCount", "quote_count", "legacy.quote_count"),
            "bookmarks": ("bookmarkCount", "bookmark_count", "legacy.bookmark_count"),
        }.items():
            count = _integer(_first(source, *paths))
            if count is not None:
                result["metrics"][key] = count
    return result


def normalize_provider_payload(
    service_id: str, canonical_url: str, payload: dict[str, Any]
) -> dict[str, Any]:
    data = _mapping(payload.get("data")) or payload
    if service_id == "instagram.profile":
        return {"profile": _profile("Instagram", canonical_url, data)}
    if service_id == "instagram.feed":
        rows = _items(_first(data, "items") or [])
        return {
            "profile": None,
            "items": [
                _content(
                    "Instagram",
                    _url(_first(row, "permalink", "link"))
                    or (
                        f"https://instagram.com/p/{_text(_first(row, 'code', 'shortcode'))}"
                        if _text(_first(row, "code", "shortcode"))
                        else ""
                    ),
                    row,
                )
                for row in rows
            ],
            "next_cursor": _text(_first(data, "next_max_id", "next_cursor")),
            "has_more": bool(_first(data, "more_available", "has_more")),
        }
    if service_id == "instagram.post":
        item = (
            _mapping(data.get("xdt_shortcode_media"))
            or _mapping(data.get("shortcode_media"))
            or data
        )
        return {"item": _content("Instagram", canonical_url, item)}
    if service_id == "instagram.stories":
        rows = _items(payload.get("items")) if "items" in payload else _items(payload)
        return {
            "profile": _profile("Instagram", canonical_url, rows[0] if rows else {}),
            "items": [
                _content("Instagram", _url(_first(row, "permalink", "link")) or "", row)
                for row in rows
            ],
            "next_cursor": None,
            "has_more": False,
        }
    if service_id == "instagram.highlight":
        rows = _items(_first(data, "items", "stories", "highlights") or [])
        return {
            "profile": None,
            "items": [
                _content(
                    "Instagram",
                    _url(_first(row, "permalink", "link")) or canonical_url,
                    row,
                )
                for row in rows
            ],
            "next_cursor": None,
            "has_more": False,
        }
    if service_id == "x.profile":
        return {"profile": _profile("X", canonical_url, data)}
    if service_id == "x.post":
        item = _mapping(_first(data, "tweet_results.result")) or data
        return {"item": _content("X", canonical_url, item)}
    if service_id == "x.feed":
        rows = _items(_first(data, "tweets", "items") or [])
        return {
            "profile": None,
            "items": [
                _content(
                    "X",
                    _url(_first(row, "url", "twitterUrl")) or "",
                    _mapping(_first(row, "tweet_results.result")) or row,
                )
                for row in rows
            ],
            "next_cursor": _text(_first(data, "cursor", "next_cursor")),
            "has_more": bool(_first(data, "has_more", "hasMore")),
        }
    if service_id == "tiktok.profile":
        return {"profile": _profile("TikTok", canonical_url, data)}
    if service_id == "tiktok.video":
        item = _mapping(data.get("aweme_detail")) or _mapping(data.get("aweme_info")) or data
        return {"item": _content("TikTok", canonical_url, item)}
    if service_id == "tiktok.feed":
        rows = _items(_first(data, "aweme_list", "itemList", "items") or [])
        cursor = _first(data, "max_cursor", "cursor", "next_cursor")
        has_more = bool(_first(data, "has_more", "hasMore"))
        return {
            "profile": None,
            "items": [
                _content("TikTok", _url(_first(row, "share_url", "webVideoUrl")) or "", row)
                for row in rows
            ],
            "next_cursor": _text(cursor),
            "has_more": has_more,
        }
    if service_id == "linkedin.profile":
        rows = _items(payload.get("items")) if "items" in payload else _items(payload)
        item = rows[0] if rows else data
        experience = []
        for row in _items(
            _first(item, "experience", "experiences", "positions", "currentPositions") or []
        ):
            experience.append(
                {
                    "title": _text(_first(row, "title", "position")),
                    "organization": _text(_first(row, "companyName", "company", "organization")),
                    "location": _text(_first(row, "location", "locationName")),
                    "started_at": _timestamp(
                        _first(row, "startDate", "startYear", "startedOn", "start")
                    ),
                    "ended_at": _timestamp(_first(row, "endDate", "endYear", "endedOn", "end")),
                    "description": _text(_first(row, "description", "summary")),
                }
            )
        education = []
        for row in _items(_first(item, "education", "educations") or []):
            education.append(
                {
                    "school": _text(
                        _first(row, "schoolName", "school", "institution", "organization")
                    ),
                    "degree": _text(_first(row, "degreeName", "degree")),
                    "field": _text(_first(row, "fieldOfStudy", "field")),
                    "started_at": _timestamp(
                        _first(row, "startDate", "startYear", "startedOn", "start")
                    ),
                    "ended_at": _timestamp(_first(row, "endDate", "endYear", "endedOn", "end")),
                }
            )
        raw_skills = _first(item, "skills") or []
        fields = {
            "headline": _text(_first(item, "headline", "title")),
            "location": _text(_first(item, "location", "geo.full")),
            "experience": experience,
            "education": education,
            "skills": [
                _text(skill.get("name") if isinstance(skill, dict) else skill)
                for skill in raw_skills
                if _text(skill.get("name") if isinstance(skill, dict) else skill)
            ]
            if isinstance(raw_skills, list)
            else [],
        }
        return {"profile": _profile("LinkedIn", canonical_url, item, service_fields=fields)}
    if service_id == "facebook.profile":
        return {"profile": _profile("Facebook", canonical_url, data)}
    if service_id == "reddit.post":
        return {"item": _content("Reddit", canonical_url, data)}
    if service_id == "youtube.channel":
        item = _mapping(data.get("channel")) or data
        fields = {
            "country": _text(_first(item, "country")),
            "joined": _text(_first(item, "joinedDateText")),
            "keywords": _first(item, "keywords")
            if isinstance(_first(item, "keywords"), list)
            else [],
        }
        return {"profile": _profile("YouTube", canonical_url, item, service_fields=fields)}
    if service_id == "youtube.video":
        return {"item": _content("YouTube", canonical_url, data)}
    if service_id == "youtube.feed":
        rows = _items(_first(data, "videos") or [])
        return {
            "profile": None,
            "items": [_content("YouTube", "", row) for row in rows],
            "next_cursor": _text(_first(data, "continuationToken", "next_cursor")),
            "has_more": bool(_first(data, "continuationToken")),
        }
    return {"item": _content("Unknown", canonical_url, data)}


def normalized_result_is_complete(service_id: str, data: dict[str, Any]) -> bool:
    """Reject provider-success envelopes that cannot satisfy the stable contract."""
    if service_id.endswith(".profile") or service_id == "youtube.channel":
        profile = _mapping(data.get("profile"))
        return bool(
            profile.get("platform")
            and profile.get("canonical_url")
            and (
                profile.get("platform_id")
                or profile.get("handle")
                and (
                    profile.get("display_name")
                    or profile.get("biography")
                    or profile.get("avatar_url")
                )
            )
        )
    if service_id in {"instagram.post", "x.post", "tiktok.video", "youtube.video", "reddit.post"}:
        item = _mapping(data.get("item"))
        author = _mapping(item.get("author"))
        has_content = bool(
            item.get("text")
            or item.get("media")
            or author.get("platform_id")
            or author.get("handle")
        )
        return bool(
            item.get("platform")
            and item.get("canonical_url")
            and item.get("platform_id")
            and has_content
        )
    return True
