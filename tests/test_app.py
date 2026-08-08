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
        assert client.get("/openapi.json").json()["servers"] == [
            {"url": "http://localhost:8000", "description": "Public ReachSocial API"}
        ]
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/readyz").json()["status"] == "ready"
        assert client.post("/mcp").status_code == 503
        assert [item["id"] for item in client.get("/v1/services").json()["services"]] == [
            "instagram.profile",
            "instagram.post",
        ]
