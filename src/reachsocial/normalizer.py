from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .errors import InvalidInput

TRACKING_PARAMETERS = {"fbclid", "gclid", "igshid", "ref", "source"}
HOST_ALIASES = {
    "www.instagram.com": "instagram.com",
    "m.instagram.com": "instagram.com",
    "www.x.com": "x.com",
    "twitter.com": "x.com",
    "www.twitter.com": "x.com",
    "mobile.twitter.com": "x.com",
    "www.tiktok.com": "tiktok.com",
    "m.tiktok.com": "tiktok.com",
    "www.linkedin.com": "linkedin.com",
    "www.youtube.com": "youtube.com",
    "youtu.be": "youtube.com",
    "www.reddit.com": "reddit.com",
    "www.facebook.com": "facebook.com",
    "m.facebook.com": "facebook.com",
}


def canonicalize_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise InvalidInput("A URL is required")
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise InvalidInput("A valid http(s) URL is required")
    host = HOST_ALIASES.get(parsed.hostname.lower(), parsed.hostname.lower())
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
        if len(segments) >= 2 and segments[0] in {"p", "reel", "tv"}:
            resource_type = "post"
        elif len(segments) >= 2 and segments[0] == "stories":
            resource_type = "stories"
            url = f"https://instagram.com/{segments[1]}"
        elif len(segments) == 1 and segments[0] not in {"explore", "accounts", "direct"}:
            resource_type = "profile"
        else:
            raise InvalidInput("This Instagram URL type is not supported")
        service_id = f"instagram.{resource_type}"
        platform = "Instagram"
    elif host == "x.com":
        if len(segments) >= 3 and segments[1] == "status" and segments[2].isdigit():
            resource_type = "post"
        elif len(segments) == 1 and segments[0] not in {"home", "search", "i", "explore"}:
            resource_type = "profile"
        else:
            raise InvalidInput("This X URL type is not supported")
        service_id = f"x.{resource_type}"
        platform = "X"
    elif host == "tiktok.com":
        if (
            len(segments) >= 3
            and segments[0].startswith("@")
            and segments[1] == "video"
            and segments[2].isdigit()
        ):
            resource_type = "video"
        elif len(segments) == 1 and segments[0].startswith("@"):
            resource_type = "profile"
        else:
            raise InvalidInput("This TikTok URL type is not supported")
        service_id = f"tiktok.{resource_type}"
        platform = "TikTok"
    elif host == "linkedin.com" and len(segments) >= 2 and segments[0] in {"in", "pub"}:
        resource_type, service_id, platform = "profile", "linkedin.profile", "LinkedIn"
    elif host == "youtube.com":
        resource_type, service_id, platform = "video", "youtube.video", "YouTube"
    elif host == "reddit.com":
        resource_type, service_id, platform = "post", "reddit.post", "Reddit"
    elif host == "facebook.com":
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
    url = canonicalize_url(value)
    parsed = urlparse(url)
    segments = [segment for segment in parsed.path.split("/") if segment]
    host = parsed.hostname or ""
    expected_host = {
        "instagram": "instagram.com",
        "x": "x.com",
        "tiktok": "tiktok.com",
        "linkedin": "linkedin.com",
    }.get(service_id.split(".", 1)[0])
    if expected_host and host != expected_host:
        raise InvalidInput(f"A canonical {expected_host} URL is required")

    if service_id in {"instagram.profile", "instagram.stories"}:
        if service_id == "instagram.stories" and len(segments) >= 2 and segments[0] == "stories":
            return f"https://instagram.com/{segments[1]}"
        if len(segments) != 1 or segments[0] in {"p", "reel", "tv", "stories", "explore"}:
            raise InvalidInput("A canonical Instagram profile URL is required")
    elif service_id == "instagram.post":
        if len(segments) < 2 or segments[0] not in {"p", "reel", "tv"}:
            raise InvalidInput("A canonical Instagram post or reel URL is required")
    elif service_id in {"x.profile", "x.feed"}:
        if len(segments) != 1 or segments[0] in {"home", "search", "i"}:
            raise InvalidInput("A canonical X profile URL is required")
    elif service_id == "x.post":
        if len(segments) < 3 or segments[1] != "status" or not segments[2].isdigit():
            raise InvalidInput("A canonical X post URL is required")
    elif service_id in {"tiktok.profile", "tiktok.feed"}:
        if len(segments) != 1 or not segments[0].startswith("@"):
            raise InvalidInput("A canonical TikTok profile URL is required")
    elif service_id == "tiktok.video":
        if (
            len(segments) < 3
            or not segments[0].startswith("@")
            or segments[1] != "video"
            or not segments[2].isdigit()
        ):
            raise InvalidInput("A canonical TikTok video URL is required")
    elif service_id == "linkedin.profile":
        if len(segments) < 2 or segments[0] not in {"in", "pub"}:
            raise InvalidInput("A canonical LinkedIn profile URL is required")
    return url
