from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .errors import InvalidInput

TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "igshid",
    "ref",
    "source",
    "trk",
}
HOST_ALIASES = {
    "instagram.com": "instagram.com",
    "www.instagram.com": "instagram.com",
    "m.instagram.com": "instagram.com",
    "x.com": "x.com",
    "www.x.com": "x.com",
    "twitter.com": "x.com",
    "www.twitter.com": "x.com",
    "mobile.twitter.com": "x.com",
    "tiktok.com": "tiktok.com",
    "www.tiktok.com": "tiktok.com",
    "m.tiktok.com": "tiktok.com",
    "linkedin.com": "linkedin.com",
    "www.linkedin.com": "linkedin.com",
    "m.linkedin.com": "linkedin.com",
    "youtube.com": "youtube.com",
    "www.youtube.com": "youtube.com",
    "m.youtube.com": "youtube.com",
    "music.youtube.com": "youtube.com",
    "youtu.be": "youtu.be",
    "reddit.com": "reddit.com",
    "www.reddit.com": "reddit.com",
    "old.reddit.com": "reddit.com",
    "redd.it": "redd.it",
    "facebook.com": "facebook.com",
    "www.facebook.com": "facebook.com",
    "m.facebook.com": "facebook.com",
    "web.facebook.com": "facebook.com",
    "fb.com": "facebook.com",
}

_INSTAGRAM_USERNAME = re.compile(r"^[A-Za-z0-9._]{1,30}$")
_INSTAGRAM_POST_ID = re.compile(r"^[A-Za-z0-9_-]{5,32}$")
_X_HANDLE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_TIKTOK_HANDLE = re.compile(r"^[A-Za-z0-9._]{2,24}$")
_LINKEDIN_SLUG = re.compile(r"^[A-Za-z0-9_-]{2,120}$")
_YOUTUBE_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{6,20}$")
_YOUTUBE_CHANNEL_ID = re.compile(r"^UC[A-Za-z0-9_-]{8,64}$")
_YOUTUBE_HANDLE = re.compile(r"^[A-Za-z0-9._-]{2,100}$")
_REDDIT_ID = re.compile(r"^[A-Za-z0-9]{3,16}$")
_REDDIT_COMMUNITY = re.compile(r"^[A-Za-z0-9_]{2,32}$")
_FACEBOOK_SLUG = re.compile(r"^[A-Za-z0-9.]{2,100}$")

_INSTAGRAM_RESERVED = {"accounts", "direct", "explore", "legal", "stories"}
_X_RESERVED = {"explore", "home", "i", "search", "settings"}
_FACEBOOK_RESERVED = {
    "events",
    "friends",
    "gaming",
    "groups",
    "help",
    "login",
    "marketplace",
    "messages",
    "notifications",
    "pages",
    "permalink.php",
    "photo",
    "photos",
    "profile.php",
    "reel",
    "reels",
    "settings",
    "share",
    "stories",
    "watch",
}


def _valid_dotted_handle(value: str, pattern: re.Pattern[str]) -> bool:
    return bool(
        pattern.fullmatch(value)
        and not value.startswith(".")
        and not value.endswith(".")
        and ".." not in value
    )


def canonicalize_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise InvalidInput("A URL is required")
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise InvalidInput("A valid http(s) URL is required")
    raw_host = parsed.hostname.lower()
    # LinkedIn serves public profiles through country subdomains such as
    # ca.linkedin.com. They carry the same profile contract as linkedin.com.
    if (
        raw_host.endswith(".linkedin.com")
        and len(raw_host.split(".", 1)[0]) == 2
        and raw_host.split(".", 1)[0].isalpha()
    ):
        host = "linkedin.com"
    else:
        host = HOST_ALIASES.get(raw_host, raw_host)
    path = "/" + "/".join(segment for segment in parsed.path.split("/") if segment)
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(
        [
            (key, item)
            for key, item in parse_qsl(parsed.query)
            if key.lower() not in TRACKING_PARAMETERS and not key.lower().startswith("utm_")
        ]
    )
    return urlunparse(("https", host, path, "", query, ""))


def resolve_url(value: object) -> dict[str, str]:
    url = canonicalize_url(value)
    parsed = urlparse(url)
    segments = [segment for segment in parsed.path.split("/") if segment]
    host = parsed.hostname or ""

    if host == "instagram.com":
        if (
            len(segments) == 2
            and segments[0].lower() in {"p", "reel", "tv"}
            and _INSTAGRAM_POST_ID.fullmatch(segments[1])
        ):
            resource_type = "post"
            url = f"https://instagram.com/{segments[0].lower()}/{segments[1]}"
        elif (
            len(segments) in {2, 3}
            and segments[0].lower() == "stories"
            and segments[1].lower() != "highlights"
            and _valid_dotted_handle(segments[1], _INSTAGRAM_USERNAME)
        ):
            resource_type = "stories"
            url = f"https://instagram.com/{segments[1].lower()}"
        elif (
            len(segments) == 1
            and segments[0].lower() not in _INSTAGRAM_RESERVED
            and _valid_dotted_handle(segments[0], _INSTAGRAM_USERNAME)
        ):
            resource_type = "profile"
            url = f"https://instagram.com/{segments[0].lower()}"
        else:
            raise InvalidInput("This Instagram URL type is not supported")
        service_id = f"instagram.{resource_type}"
        platform = "Instagram"
    elif host == "x.com":
        if (
            len(segments) == 3
            and _X_HANDLE.fullmatch(segments[0])
            and segments[1].lower() == "status"
            and segments[2].isdigit()
        ):
            resource_type = "post"
            url = f"https://x.com/{segments[0].lower()}/status/{segments[2]}"
        elif (
            len(segments) == 1
            and segments[0].lower() not in _X_RESERVED
            and _X_HANDLE.fullmatch(segments[0])
        ):
            resource_type = "profile"
            url = f"https://x.com/{segments[0].lower()}"
        else:
            raise InvalidInput("This X URL type is not supported")
        service_id = f"x.{resource_type}"
        platform = "X"
    elif host == "tiktok.com":
        if (
            len(segments) == 3
            and segments[0].startswith("@")
            and _valid_dotted_handle(segments[0][1:], _TIKTOK_HANDLE)
            and segments[1].lower() == "video"
            and segments[2].isdigit()
        ):
            resource_type = "video"
            url = f"https://tiktok.com/@{segments[0][1:].lower()}/video/{segments[2]}"
        elif (
            len(segments) == 1
            and segments[0].startswith("@")
            and _valid_dotted_handle(segments[0][1:], _TIKTOK_HANDLE)
        ):
            resource_type = "profile"
            url = f"https://tiktok.com/@{segments[0][1:].lower()}"
        else:
            raise InvalidInput("This TikTok URL type is not supported")
        service_id = f"tiktok.{resource_type}"
        platform = "TikTok"
    elif (
        host == "linkedin.com"
        and len(segments) == 2
        and segments[0].lower() in {"in", "pub"}
        and _LINKEDIN_SLUG.fullmatch(segments[1])
    ):
        resource_type, service_id, platform = "profile", "linkedin.profile", "LinkedIn"
        url = f"https://linkedin.com/{segments[0].lower()}/{segments[1]}"
    elif host in {"youtube.com", "youtu.be"}:
        video_id = ""
        if host == "youtu.be" and len(segments) == 1:
            video_id = segments[0]
        elif host == "youtube.com" and parsed.path == "/watch":
            video_id = dict(parse_qsl(parsed.query)).get("v", "")
        elif (
            host == "youtube.com"
            and len(segments) == 2
            and segments[0]
            in {
                "embed",
                "live",
                "shorts",
            }
        ):
            video_id = segments[1]
        if _YOUTUBE_VIDEO_ID.fullmatch(video_id):
            url = f"https://youtube.com/watch?v={video_id}"
            resource_type, service_id = "video", "youtube.video"
        else:
            channel_kind = ""
            channel_value = ""
            if host == "youtube.com" and segments:
                if segments[0].startswith("@"):
                    channel_kind, channel_value = "@", segments[0][1:]
                elif len(segments) >= 2 and segments[0].lower() in {
                    "c",
                    "channel",
                    "user",
                }:
                    channel_kind, channel_value = segments[0].lower(), segments[1]
            is_channel = (
                (channel_kind == "@" and bool(_YOUTUBE_HANDLE.fullmatch(channel_value)))
                or (
                    channel_kind == "channel" and bool(_YOUTUBE_CHANNEL_ID.fullmatch(channel_value))
                )
                or (
                    channel_kind in {"c", "user"} and bool(_YOUTUBE_HANDLE.fullmatch(channel_value))
                )
            )
            if not is_channel:
                raise InvalidInput("This YouTube URL type is not supported")
            prefix = "@" if channel_kind == "@" else f"{channel_kind}/"
            url = f"https://youtube.com/{prefix}{channel_value}"
            resource_type, service_id = "channel", "youtube.channel"
        platform = "YouTube"
    elif host in {"reddit.com", "redd.it"}:
        post_id = ""
        if host == "redd.it" and len(segments) == 1:
            post_id = segments[0]
        elif (
            host == "reddit.com"
            and len(segments) >= 4
            and segments[0].lower() == "r"
            and _REDDIT_COMMUNITY.fullmatch(segments[1])
            and segments[2].lower() == "comments"
        ):
            post_id = segments[3]
        elif host == "reddit.com" and len(segments) >= 2 and segments[0].lower() == "comments":
            post_id = segments[1]
        if not _REDDIT_ID.fullmatch(post_id):
            raise InvalidInput("This Reddit URL type is not supported")
        url = f"https://reddit.com/comments/{post_id}"
        resource_type, service_id, platform = "post", "reddit.post", "Reddit"
    elif host == "facebook.com":
        query = dict(parse_qsl(parsed.query))
        is_numeric_profile = parsed.path == "/profile.php" and str(query.get("id") or "").isdigit()
        is_named_profile = (
            len(segments) == 1
            and segments[0].lower() not in _FACEBOOK_RESERVED
            and bool(_FACEBOOK_SLUG.fullmatch(segments[0]))
        )
        is_people_profile = (
            len(segments) == 3 and segments[0].lower() == "people" and segments[2].isdigit()
        )
        if not (is_numeric_profile or is_named_profile or is_people_profile):
            raise InvalidInput("This Facebook URL type is not supported")
        if is_numeric_profile:
            url = f"https://facebook.com/profile.php?id={query['id']}"
        elif is_people_profile:
            url = f"https://facebook.com/people/{segments[1]}/{segments[2]}"
        else:
            url = f"https://facebook.com/{segments[0].lower()}"
        resource_type, service_id, platform = "profile", "facebook.profile", "Facebook"
    else:
        raise InvalidInput("This social URL is not supported")
    return {
        "platform": platform,
        "resource_type": resource_type,
        "canonical_url": url,
        "service_id": service_id,
    }


def validate_service_url(service_id: str, value: object) -> str:
    resolved = resolve_url(value)
    accepted_resolution = {
        "instagram.feed": {"instagram.profile"},
        "instagram.stories": {"instagram.profile", "instagram.stories"},
        "x.feed": {"x.profile"},
        "tiktok.feed": {"tiktok.profile"},
        "youtube.feed": {"youtube.channel"},
    }.get(service_id, {service_id})
    if resolved["service_id"] not in accepted_resolution:
        raise InvalidInput(f"A URL for {service_id} is required")
    return resolved["canonical_url"]
