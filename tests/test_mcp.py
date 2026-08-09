from __future__ import annotations

import asyncio

from reachsocial.catalog import load_catalog
from reachsocial.mcp import make_mcp_server


def test_mcp_exposes_exact_sync_and_async_b2b_tools() -> None:
    tools = asyncio.run(make_mcp_server(load_catalog()).list_tools())
    by_name = {tool.name: tool for tool in tools}
    assert set(by_name) == {
        "instagram_profile",
        "instagram_post",
        "start_linkedin_profile",
        "get_reachsocial_job",
    }
    assert set(by_name["instagram_profile"].input_schema["properties"]) == {
        "url",
        "idempotency_key",
    }
    assert set(by_name["start_linkedin_profile"].input_schema["properties"]) == {
        "url",
        "idempotency_key",
    }
    assert by_name["get_reachsocial_job"].input_schema["required"] == ["job_id"]
