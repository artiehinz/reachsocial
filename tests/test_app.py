from fastapi.testclient import TestClient

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
        assert openapi["paths"]["/v1/services/{service_id}/execute"]["post"][
            "responses"
        ]["402"]["headers"]["PAYMENT-REQUIRED"]
        assert len(openapi["x-reachsocial-services"]) == 13
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/readyz").json()["status"] == "ready"
        assert client.post("/mcp").status_code == 503
        assert client.get("/mcp/server-card").status_code == 503
        assert client.get("/.well-known/mcp.json").status_code == 503
        assert [item["id"] for item in client.get("/v1/services").json()["services"]] == [
            "instagram.profile",
            "instagram.post",
            "linkedin.profile",
        ]
        services = client.get("/v1/services").json()["services"]
        assert all(item["schema_version"] == "1.0" for item in services)
        assert [item["execution"] for item in services] == ["sync", "sync", "async"]
        roadmap = client.get("/v1/catalog").json()
        assert roadmap["summary"] == {
            "available": 3,
            "validation": 5,
            "planned": 3,
            "paused": 2,
            "platforms": 7,
        }
        assert client.get("/services/x.feed").status_code == 200
        assert client.get("/services/linkedin.profile").status_code == 200
        assert "X Latest Feed" in client.get("/catalog").text
        assert "Paused" in client.get("/services/x.feed").text
        assert "LinkedIn Profile Enrichment" in client.get("/catalog").text
        llms = client.get("/llms.txt")
        assert llms.headers["content-type"].startswith("text/plain")
        assert llms.text.startswith("# ReachSocial")
        assert "linkedin.profile" in llms.text
        assert client.get("/agent.md").headers["content-type"].startswith("text/markdown")
        assert client.get("/.well-known/api-catalog").headers["content-type"].startswith(
            "application/linkset+json"
        )
        assert client.get("/robots.txt").status_code == 200
        assert client.get("/sitemap.xml").status_code == 200
