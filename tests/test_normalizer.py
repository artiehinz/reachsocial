import pytest

from reachsocial.errors import InvalidInput
from reachsocial.normalizer import resolve_url


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
