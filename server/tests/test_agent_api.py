from fastapi.testclient import TestClient

from app.main import app


def test_agent_status_endpoint_returns_runtime_configuration() -> None:
    client = TestClient(app)

    response = client.get("/api/agent/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "mock"
    assert payload["active_mode"] == "mock"
    assert payload["model"]
    assert payload["openai_configured"] is False


def test_music_status_endpoint_returns_netease_health_payload() -> None:
    client = TestClient(app)

    response = client.get("/api/agent/music")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "netease_cloud_music"
    assert "account" in payload
    assert "search_ok" in payload
