"""Local acceptance checkpoints must survive restarts without retaining secrets."""

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def acceptance():
    path = Path(__file__).parents[1] / "scripts/mcp_browser_acceptance.py"
    spec = importlib.util.spec_from_file_location("mcp_acceptance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_checkpoint_is_atomic_private_and_preserves_original_on_failure(
    acceptance, tmp_path, monkeypatch
):
    path = tmp_path / "state.json"
    original = {"key": "original-request", "request_id": "original-id"}
    acceptance.save(path, original)
    assert path.stat().st_mode & 0o777 == 0o600

    def fail(*_):
        raise OSError("simulated failed replacement")

    monkeypatch.setattr(acceptance.os, "replace", fail)
    with pytest.raises(OSError):
        acceptance.save(path, {"key": "replacement"})
    assert json.loads(path.read_text()) == original
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize(
    "arguments", [[], ["--confirm-mainnet-payments", "--max-total-atomic", "100000"]]
)
def test_acceptance_requires_exact_bounded_confirmation(acceptance, monkeypatch, arguments):
    monkeypatch.setattr(
        "sys.argv", ["acceptance", "--expected-pay-to", "public-address", *arguments]
    )
    monkeypatch.setattr(
        acceptance.httpx, "Client", lambda **_: pytest.fail("No network request permitted")
    )
    with pytest.raises(SystemExit) as error:
        acceptance.main()
    assert error.value.code == 2


def test_os_error_diagnostic_does_not_expose_exception_text(acceptance):
    import errno

    message = acceptance.failure_message(OSError(errno.EADDRINUSE, "sensitive exception details"))
    assert "callback port is busy" in message
    assert "Keep the checkpoint" in message
    assert "sensitive exception details" not in message
    permission = acceptance.failure_message(PermissionError(errno.EACCES, "sensitive path"))
    assert "checkpoint ownership" in permission
    assert "sensitive path" not in permission


def test_private_stage_requires_explicit_lane_and_reviewed_five_cent_sync_service(acceptance):
    service = {"id": "instagram.feed", "price_cents": 5, "execution": "sync",
               "status": "private", "available": False}
    assert acceptance.acceptance_service([service], "instagram.feed", True)
    assert acceptance.acceptance_service([{**service, "price_cents": None}], "instagram.feed", True)
    assert not acceptance.acceptance_service([service], "instagram.feed", False)
    for changed in [{"id": "news.person"}, {"price_cents": 10}, {"execution": "async"},
                    {"status": "available"}, {"status": "paused"}]:
        candidate = {**service, **changed}
        assert not acceptance.acceptance_service([candidate], candidate["id"], True)
    public = {**service, "status": "available", "available": True}
    assert acceptance.acceptance_service([public], "instagram.feed", False)
