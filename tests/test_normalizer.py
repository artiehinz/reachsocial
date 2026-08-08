import pytest

from reachsocial.errors import InvalidInput
from reachsocial.normalizer import resolve_url


def test_resolve_x_status_url_and_remove_tracking() -> None:
    result = resolve_url("https://twitter.com/example/status/123?utm_source=test&fbclid=remove")
    assert result == {
        "platform": "X",
        "resource_type": "post",
        "canonical_url": "https://x.com/example/status/123?utm_source=test",
        "service_id": "x.post",
    }


def test_reject_unsupported_url() -> None:
    with pytest.raises(InvalidInput):
        resolve_url("https://example.com/nope")
