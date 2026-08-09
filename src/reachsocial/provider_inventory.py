from __future__ import annotations

import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

DEFAULT_SOURCE = "https://docs.scrapecreators.com/openapi.json"
METHODS = {"get", "post", "put", "patch", "delete"}
EXCLUDED_PREFIXES = ("/v1/account/", "/v1/credit-", "/v1/detect-age-gender")
HIGH_REVIEW_TERMS = {
    "audience",
    "followers",
    "following",
    "email",
    "age",
    "gender",
    "marketplace",
    "ads",
    "adlibrary",
}


def load_openapi(source: str) -> dict[str, Any]:
    path = Path(source)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    response = httpx.get(source, timeout=30, follow_redirects=True)
    response.raise_for_status()
    return response.json()


def _platform(path: str, operation: dict[str, Any]) -> str:
    tags = operation.get("tags")
    if isinstance(tags, list) and tags and isinstance(tags[0], str):
        return tags[0]
    parts = [part for part in path.split("/") if part]
    if parts and re.fullmatch(r"v\d+", parts[0]):
        parts = parts[1:]
    return (parts[0] if parts else "Other").replace("-", " ").title()


def _capability_id(path: str, method: str) -> str:
    parts = [part for part in path.split("/") if part]
    if parts and re.fullmatch(r"v\d+", parts[0]):
        parts = parts[1:]
    value = ".".join(re.sub(r"([a-z])([A-Z])", r"\1-\2", part).lower() for part in parts)
    return value + (".post" if method == "post" and not value.endswith(".post") else "")


def build_inventory(spec: dict[str, Any], *, source: str) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for path, path_item in sorted((spec.get("paths") or {}).items()):
        if not isinstance(path_item, dict):
            continue
        for method, operation in sorted(path_item.items()):
            if method not in METHODS or not isinstance(operation, dict):
                continue
            lowered = path.lower()
            review_flags = sorted(term for term in HIGH_REVIEW_TERMS if term in lowered)
            excluded = path.startswith(EXCLUDED_PREFIXES)
            parameters = operation.get("parameters") or []
            parameter_names = sorted(
                {
                    str(item.get("name"))
                    for item in parameters
                    if isinstance(item, dict) and item.get("name")
                }
            )
            candidates.append(
                {
                    "candidate_id": _capability_id(path, method),
                    "platform": _platform(path, operation),
                    "title": operation.get("summary") or operation.get("operationId") or path,
                    "method": method.upper(),
                    "upstream_path": path,
                    "parameters": parameter_names,
                    "review_state": "excluded" if excluded else "unreviewed",
                    "review_flags": review_flags,
                    "deprecated": bool(operation.get("deprecated")),
                }
            )
    states = Counter(item["review_state"] for item in candidates)
    platforms = Counter(item["platform"] for item in candidates if item["review_state"] != "excluded")
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "source": source,
        "notice": (
            "Review-only provider inventory. Entries are not ReachSocial services, are not "
            "priced, and must never be enabled without a normalized contract and live cost test."
        ),
        "summary": {
            "operations": len(candidates),
            "unreviewed": states["unreviewed"],
            "excluded": states["excluded"],
            "platforms": dict(sorted(platforms.items())),
        },
        "candidates": candidates,
    }
