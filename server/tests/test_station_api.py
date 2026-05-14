from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.main import app


def test_station_generate_returns_session_payload() -> None:
    client = TestClient(app)

    response = client.post("/api/station/generate", json=make_generate_payload())

    assert response.status_code == 200
    payload = response.json()
    session = payload["session"]
    assert session["session_id"].startswith("session-")
    assert session["program"]["title"]
    assert session["calendar_events"]
    assert session["greeting"]
    assert payload["runtime"]["brain"]["provider"] == "mock"


def test_station_chat_returns_reply_and_session() -> None:
    client = TestClient(app)
    payload = make_generate_payload()
    client.post("/api/station/generate", json=payload)

    response = client.post(
        "/api/chat",
        json={
            "user_id": payload["user_id"],
            "message": "我想更安静一点，不要太满。",
            "device_context": payload["device_context"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "我想更安静一点" in body["reply"]["text"]
    assert body["session"]["program"]["title"]


def test_player_now_returns_current_item_after_station_generation() -> None:
    client = TestClient(app)
    payload = make_generate_payload()
    client.post("/api/station/generate", json=payload)

    response = client.get(f"/api/player/{payload['user_id']}/now")

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["user_id"] == payload["user_id"]
    assert body["current_item"] is not None
    assert body["queue"]


def test_runtime_status_reports_provider_boundaries() -> None:
    client = TestClient(app)

    response = client.get("/api/runtime/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["brain"]["provider"] == "mock"
    assert payload["tts"]["provider"] == "mock"
    assert payload["calendar"]["provider"] == "mock"


def test_station_api_allows_local_web_origin() -> None:
    client = TestClient(app)

    response = client.options(
        "/api/station/generate",
        headers={
            "Origin": "http://127.0.0.1:8081",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:8081"


def test_station_chat_regenerates_a_fresh_session() -> None:
    client = TestClient(app)
    payload = make_generate_payload()
    first_response = client.post("/api/station/generate", json=payload)
    chat_response = client.post(
        "/api/chat",
        json={
            "user_id": payload["user_id"],
            "message": "regenerate the station around a quieter mood",
            "device_context": payload["device_context"],
        },
    )

    assert first_response.status_code == 200
    assert chat_response.status_code == 200
    first_session_id = first_response.json()["session"]["session_id"]
    second_session_id = chat_response.json()["session"]["session_id"]
    assert second_session_id.startswith("session-")
    assert second_session_id != first_session_id


def test_station_chat_first_request_creates_single_session_without_seed_roundtrip() -> None:
    client = TestClient(app)
    payload = make_generate_payload()

    response = client.post(
        "/api/chat",
        json={
            "user_id": payload["user_id"],
            "message": "想听一点更安静的中文歌",
            "device_context": payload["device_context"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["session_id"].startswith("session-")
    assert "安静" in body["reply"]["text"]


def make_generate_payload() -> dict[str, object]:
    return {
        "user_id": "station-api-user",
        "device_context": {
            "local_time": datetime(2026, 4, 30, 22, 30, tzinfo=UTC).isoformat(),
            "timezone": "Asia/Shanghai",
            "locale": "zh-CN",
            "city_hint": "Shanghai",
            "latitude": 31.2304,
            "longitude": 121.4737,
        },
        "user_state": {
            "mood": "tired",
            "energy_level": 2,
            "needs": ["relax", "companionship"],
            "duration_minutes": 25,
            "free_text": "今晚想听一档有人陪着我的电台。",
        },
        "max_candidates": 10,
    }
