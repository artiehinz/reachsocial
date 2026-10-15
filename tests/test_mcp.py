from __future__ import annotations

import asyncio

from reachsocial.catalog import load_catalog
from reachsocial.config import get_settings
from reachsocial.mcp import make_mcp_server


def test_mcp_exposes_exact_sync_and_async_b2b_tools() -> None:
    tools = asyncio.run(make_mcp_server(load_catalog()).list_tools())
    by_name = {tool.name: tool for tool in tools}
    assert set(by_name) == {
        "instagram_profile",
        "instagram_post",
        "x_profile",
        "x_post",
        "x_feed",
        "tiktok_profile",
        "tiktok_feed",
        "tiktok_video",
    }
    assert set(by_name["instagram_profile"].input_schema["properties"]) == {
        "url",
        "idempotency_key",
    }


def test_owner_validation_tools_are_not_listed_in_the_public_server_card(monkeypatch) -> None:
    with monkeypatch.context() as environment:
        environment.setenv("OAUTH_ENABLED", "true")
        environment.setenv("OAUTH_VALIDATION_WALLETS", "0x" + "11" * 20)
        environment.setenv("MAINNET_PRIVATE_ACCEPTANCE_ENABLED", "true")
        environment.setenv("MAINNET_PRIVATE_ACCEPTANCE_SERVICES", "instagram.feed")
        get_settings.cache_clear()
        catalog = load_catalog()
        public_names = {
            tool.name for tool in asyncio.run(make_mcp_server(catalog).list_tools())
        }
        validation_names = {
            tool.name
            for tool in asyncio.run(
                make_mcp_server(catalog, include_private_validation=True).list_tools()
            )
        }
        assert "instagram_feed" not in public_names
        assert "instagram_feed" in validation_names
    get_settings.cache_clear()
