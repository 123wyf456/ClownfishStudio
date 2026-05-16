from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.main import app
from app.schemas import CandidateItem, ContentType, GenerateProgramResponse
from app.services import station_orchestrator


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
    assert session["playlist"]["current_index"] == 0
    assert 1 <= len(session["playlist"]["items"]) <= 8
    assert session["tts_text"] is None
    assert session["tts_audio_url"] is None
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
    assert body["reply"]["text"]
    assert len(body["reply"]["text"]) <= 36
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
    assert body["playlist"]["items"]


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


def test_station_chat_only_keeps_current_session() -> None:
    client = TestClient(app)
    payload = make_generate_payload()
    first_response = client.post("/api/station/generate", json=payload)
    chat_response = client.post(
        "/api/chat",
        json={
            "user_id": payload["user_id"],
            "message": "今天确实有点累",
            "device_context": payload["device_context"],
        },
    )

    assert first_response.status_code == 200
    assert chat_response.status_code == 200
    first_session_id = first_response.json()["session"]["session_id"]
    second_session_id = chat_response.json()["session"]["session_id"]
    assert second_session_id == first_session_id
    assert chat_response.json()["reply"]["text"]


def test_station_chat_retunes_playlist_without_creating_a_new_session() -> None:
    client = TestClient(app)
    payload = make_generate_payload()
    first_response = client.post("/api/station/generate", json=payload)
    first_playlist = first_response.json()["session"]["playlist"]
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
    second_playlist = chat_response.json()["session"]["playlist"]
    assert second_session_id == first_session_id
    assert second_playlist["current_index"] == first_playlist["current_index"]
    assert second_playlist["items"][second_playlist["current_index"]]["item_id"] == (
        first_playlist["items"][first_playlist["current_index"]]["item_id"]
    )


def test_player_advance_moves_current_index_and_returns_playlist() -> None:
    client = TestClient(app)
    payload = make_generate_payload()
    generate_response = client.post("/api/station/generate", json=payload)
    playlist = generate_response.json()["session"]["playlist"]
    current_item = playlist["items"][0]

    response = client.post(
        f"/api/player/{payload['user_id']}/advance",
        json={"item_id": current_item["item_id"], "reason": "ended"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["playlist"]["current_index"] == 1
    assert body["current_item"]["item_id"] == body["playlist"]["items"][1]["item_id"]
    assert len(body["queue"]) <= 8


def test_player_advance_does_not_refill_synchronously(monkeypatch) -> None:
    client = TestClient(app)
    payload = make_generate_payload()
    generate_response = client.post("/api/station/generate", json=payload)
    playlist = generate_response.json()["session"]["playlist"]
    current_item = playlist["items"][0]

    def fail_generate(*args, **kwargs):  # noqa: ANN002, ANN003
        del args, kwargs
        raise AssertionError("advance should not generate refill candidates")

    monkeypatch.setattr(
        station_orchestrator.ProgramGenerationService,
        "generate",
        fail_generate,
    )

    response = client.post(
        f"/api/player/{payload['user_id']}/advance",
        json={"item_id": current_item["item_id"], "reason": "ended"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["playlist"]["current_index"] == 1
    assert "Playlist refill is needed" in " ".join(body["warnings"])


def test_player_refill_extends_playlist_when_remaining_is_low(monkeypatch) -> None:
    client = TestClient(app)
    payload = make_generate_payload()
    generate_response = client.post("/api/station/generate", json=payload)
    playlist = generate_response.json()["session"]["playlist"]
    current_item = playlist["items"][0]
    response = client.post(
        f"/api/player/{payload['user_id']}/advance",
        json={"item_id": current_item["item_id"], "reason": "ended"},
    )
    seed_program = response.json()["session"]["program"]

    def fake_generate(self, request, chat_history=None):  # noqa: ANN001
        del self, request, chat_history
        candidate_items = [
            CandidateItem(
                candidate_id=f"refill-{index}",
                content_type=ContentType.music,
                title=f"Refill Song {index}",
                creator="Refill Artist",
                duration_seconds=180,
                playback_url=f"https://example.com/refill-{index}.mp3",
                tags=["search_result"],
                source="netease_cloud_music",
            )
            for index in range(4)
        ]
        return GenerateProgramResponse(
            request_id="request-refill",
            program=seed_program,
            candidate_count=len(candidate_items),
            candidate_items=candidate_items,
        )

    monkeypatch.setattr(
        station_orchestrator.ProgramGenerationService,
        "generate",
        fake_generate,
    )

    refill_response = client.post(f"/api/player/{payload['user_id']}/refill")

    assert refill_response.status_code == 200
    body = refill_response.json()
    candidate_ids = [item["candidate_id"] for item in body["playlist"]["items"]]
    assert "refill-0" in candidate_ids
    assert body["current_item"]["item_id"] == (
        body["playlist"]["items"][body["playlist"]["current_index"]]["item_id"]
    )


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
    assert body["reply"]["text"]
    assert len(body["reply"]["text"]) <= 36


def test_station_chat_song_request_returns_422_when_only_mock_candidates_exist(monkeypatch) -> None:
    client = TestClient(app)
    payload = make_generate_payload()
    seed_response = client.post("/api/station/generate", json=payload)
    seed_program = seed_response.json()["session"]["program"]

    def fake_generate(self, request, chat_history=None):  # noqa: ANN001
        del self, request, chat_history
        candidate_items = [
            CandidateItem(
                candidate_id="mock-song-1",
                content_type=ContentType.music,
                title="Mock Song",
                creator="Mock Artist",
                duration_seconds=180,
                playback_url="https://example.com/mock-song.mp3",
                tags=["search_result"],
                source="mock",
            )
        ]
        return GenerateProgramResponse(
            request_id="request-mock",
            program=seed_program,
            candidate_count=len(candidate_items),
            candidate_items=candidate_items,
        )

    monkeypatch.setattr(
        station_orchestrator.ProgramGenerationService,
        "generate",
        fake_generate,
    )

    response = client.post(
        "/api/chat",
        json={
            "user_id": payload["user_id"],
            "message": "给我来一首歌",
            "device_context": payload["device_context"],
        },
    )

    assert response.status_code == 422
    assert "真实歌曲" in response.json()["detail"]


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
