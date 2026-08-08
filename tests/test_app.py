from fastapi.testclient import TestClient

from reachsocial.main import app


def test_health_and_mcp_gate() -> None:
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/readyz").json()["status"] == "ready"
        assert client.post("/mcp").status_code == 503
        assert [item["id"] for item in client.get("/v1/services").json()["services"]] == [
            "instagram.profile",
            "instagram.post",
        ]
