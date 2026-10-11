from fastapi.testclient import TestClient

from reachsocial.api import ExecuteRequest, resolve
from reachsocial.config import x402_network_label
from reachsocial.main import app


def test_health_and_mcp_gate() -> None:
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/catalog").status_code == 200
        assert client.get("/pricing").status_code == 200
        assert client.get("/status").status_code == 200
        assert client.get("/status.json").json()["status"] == "operational"
        assert client.get("/contact").status_code == 200
        assert client.get("/legal/terms").status_code == 200
        assert client.get("/legal/privacy").status_code == 200
        assert client.get("/legal/acceptable-use").status_code == 200
        assert client.get("/legal/refunds").status_code == 200
        assert client.get("/docs/api").status_code == 200
        assert "Base Sepolia" in client.get("/pricing").text
        openapi = client.get("/openapi.json").json()
        assert openapi["servers"] == [
            {"url": "http://localhost:8000", "description": "Public ReachSocial API"}
        ]
        assert set(openapi["components"]["securitySchemes"]) == {
            "adminToken",
            "bearerAuth",
            "jobToken",
            "x402Payment",
        }
        assert openapi["paths"]["/v1/jobs/{job_id}"]["get"]["security"] == [
            {"bearerAuth": []},
            {"jobToken": []},
        ]
        assert openapi["paths"]["/v1/services/{service_id}/execute"]["post"]["responses"]["402"][
            "headers"
        ]["PAYMENT-REQUIRED"]
        assert len(openapi["x-reachsocial-services"]) == 18
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/readyz").json()["status"] == "ready"
        assert client.post("/mcp").status_code == 503
        assert client.get("/mcp/server-card").status_code == 503
        assert client.get("/.well-known/mcp.json").status_code == 503
        assert [item["id"] for item in client.get("/v1/services").json()["services"]] == [
            "instagram.profile",
            "instagram.post",
            "x.profile",
            "x.post",
            "x.feed",
            "tiktok.profile",
            "tiktok.feed",
            "tiktok.video",
        ]
        services = client.get("/v1/services").json()["services"]
        assert all(item["schema_version"] == "1.0" for item in services)
        assert [item["execution"] for item in services] == ["sync"] * 8
        roadmap = client.get("/v1/catalog").json()
        assert roadmap["summary"] == {
            "available": 8,
            "private": 7,
            "validation": 0,
            "planned": 0,
            "paused": 3,
            "platforms": 8,
        }
        assert client.get("/services/x.feed").status_code == 200
        assert client.get("/services/linkedin.profile").status_code == 200
        home = client.get("/").text
        catalog_page = client.get("/catalog").text
        assert 'href="/catalog#x"' in home
        assert 'data-copy-target="agent-prompt"' in home
        assert "artie_hinz" not in home
        assert "artie_hinz" not in client.get("/docs/api").text
        copy_script = client.get("/static/site.js").text
        assert "navigator.clipboard.writeText" in copy_script
        assert "Select and copy the prompt manually." in copy_script
        assert 'class="section-heading" id="x"' in catalog_page
        assert "X Public Posts" in catalog_page
        assert "Available" in client.get("/services/x.feed").text
        assert "LinkedIn Public Profile" in catalog_page
        assert "artie_hinz" not in client.get("/services/instagram.profile").text
        assert "DI2B5I4gsQY" not in client.get("/services/instagram.post").text
        llms = client.get("/llms.txt")
        assert llms.headers["content-type"].startswith("text/plain")
        assert llms.text.startswith("# ReachSocial")
        assert "instagram.profile" in llms.text
        assert client.get("/agent.md").headers["content-type"].startswith("text/markdown")
        assert (
            client.get("/.well-known/api-catalog")
            .headers["content-type"]
            .startswith("application/linkset+json")
        )
        assert client.get("/robots.txt").status_code == 200
        assert client.get("/sitemap.xml").status_code == 200


def test_x402_network_label_tracks_the_selected_network() -> None:
    assert x402_network_label("eip155:8453") == "Base mainnet"
    assert x402_network_label("eip155:84532") == "Base Sepolia"


def test_readiness_reports_an_automatic_payment_pause() -> None:
    with TestClient(app) as client:
        app.state.runtime.pause_public_payments("provider_failures")
        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.json() == {
            "status": "payments_paused",
            "reason": "provider_failures",
        }
        app.state.runtime.public_payments_paused_reason = None


def test_cache_headers_only_allow_public_get_routes() -> None:
    with TestClient(app) as client:
        assert client.get("/v1/catalog").headers["cache-control"] == (
            "public, max-age=60, s-maxage=300, stale-while-revalidate=600"
        )
        assert client.get("/catalog").headers["cache-control"] == (
            "public, max-age=60, s-maxage=120, stale-while-revalidate=300"
        )
        assert client.get("/healthz").headers["cache-control"] == "no-store"
        assert client.post("/v1/resolve", json={"input": {}}).headers["cache-control"] == "no-store"


def test_resolve_requires_authentication() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/v1/resolve",
            json={"input": {"url": "https://instagram.com/openai"}},
        )
    assert response.status_code == 401


def test_resolve_reports_catalog_state_without_provider_details(session, client, catalog) -> None:
    result = resolve(
        ExecuteRequest(input={"url": "https://www.instagram.com/openai/"}),
        client,
        session,
        catalog,
    )

    assert result == {
        "schema_version": "1.0",
        "platform": "Instagram",
        "resource_type": "profile",
        "canonical_url": "https://instagram.com/openai",
        "service_id": "instagram.profile",
        "execution": "sync",
        "status": "available",
        "executable": True,
    }


def test_public_page_headers_and_live_mcp_status(monkeypatch) -> None:
    with TestClient(app) as client:
        home = client.get("/")
        assert home.headers["x-content-type-options"] == "nosniff"
        assert "frame-ancestors 'none'" in home.headers["content-security-policy"]
        assert "script-src 'none'" in home.headers["content-security-policy"]
        assert client.get("/healthz").headers["cache-control"] == "no-store"
        monkeypatch.setattr(app.state.settings, "mcp_enabled", True)
        assert "MCP is available to approved B2B clients" in client.get("/status").text
        monkeypatch.setattr(app.state.settings, "mcp_enabled", False)
        assert "MCP is disabled" in client.get("/status").text
