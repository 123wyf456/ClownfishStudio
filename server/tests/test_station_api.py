from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.schemas import CandidateItem, ContentType, GenerateProgramResponse
from app.services import station_orchestrator, station_tts
from app.services.session_store import get_station_session
from app.tools import list_feedback_events, list_memory_update_hints
from app.tools import netease_music_tool as netease_module


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
    assert session["tts_text"] == session["greeting"]
    assert session["tts_audio_url"].startswith("/mock-audio/")
    assert payload["runtime"]["brain"]["provider"] == "mock"


def test_station_generate_reports_netease_api_error(monkeypatch) -> None:
    monkeypatch.setenv("NETEASE_API_BASE_URL", "http://127.0.0.1:9")
    get_settings.cache_clear()
    monkeypatch.setattr(
        netease_module,
        "_get_preference_snapshot",
        lambda **kwargs: (_ for _ in ()).throw(
            netease_module.NeteaseMusicToolError("connection refused")
        ),
    )
    monkeypatch.setattr(
        "app.tools.music_search_tool.search_netease_music_candidates",
        lambda **kwargs: (_ for _ in ()).throw(
            netease_module.NeteaseMusicToolError("connection refused")
        ),
    )
    client = TestClient(app)

    response = client.post("/api/station/generate", json=make_generate_payload())

    assert response.status_code == 503
    payload = response.json()
    assert "网易云音乐服务连接失败" in payload["detail"]
    assert "connection refused" in payload["detail"]


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
    assert body["reply"]["metadata"]["reply_kind"] in {"music", "chat", "control", "info"}
    assert body["reply"]["metadata"]["reply_source"] in {"agent", "fallback", "control"}
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
    assert (
        second_playlist["items"][second_playlist["current_index"]]["item_id"]
        == (first_playlist["items"][first_playlist["current_index"]]["item_id"])
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


def test_station_chat_control_skip_advances_playlist_without_regeneration() -> None:
    client = TestClient(app)
    payload = make_generate_payload()
    generate_response = client.post("/api/station/generate", json=payload)
    first_playlist = generate_response.json()["session"]["playlist"]

    response = client.post(
        "/api/chat",
        json={
            "user_id": payload["user_id"],
            "message": "跳过这首",
            "device_context": payload["device_context"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reply"]["text"]
    assert body["session"]["session_id"] == generate_response.json()["session"]["session_id"]
    assert body["session"]["playlist"]["current_index"] == min(
        1,
        len(first_playlist["items"]) - 1,
    )


def test_station_chat_info_question_uses_dj_reply_without_retuning() -> None:
    client = TestClient(app)
    payload = make_generate_payload()
    generate_response = client.post("/api/station/generate", json=payload)
    first_session = generate_response.json()["session"]
    first_playlist = first_session["playlist"]

    response = client.post(
        "/api/chat",
        json={
            "user_id": payload["user_id"],
            "message": "这首歌是谁唱的",
            "device_context": payload["device_context"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reply"]["text"]
    assert body["session"]["session_id"] == first_session["session_id"]
    assert body["session"]["playlist"]["revision"] == first_playlist["revision"]


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
    assert (
        body["current_item"]["item_id"]
        == (body["playlist"]["items"][body["playlist"]["current_index"]]["item_id"])
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


def test_station_chat_song_request_accepts_real_music_candidates(monkeypatch) -> None:
    client = TestClient(app)
    payload = make_generate_payload()
    seed_response = client.post("/api/station/generate", json=payload)
    seed_program = seed_response.json()["session"]["program"]

    def fake_generate(self, request, chat_history=None):  # noqa: ANN001
        del self, request, chat_history
        candidate_items = [
            CandidateItem(
                candidate_id="netease-real-1",
                content_type=ContentType.music,
                title="Real Song",
                creator="Real Artist",
                duration_seconds=180,
                playback_url="https://example.com/real-song.mp3",
                tags=["search_result"],
                source="netease_cloud_music",
            )
        ]
        return GenerateProgramResponse(
            request_id="request-real",
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

    assert response.status_code == 200
    assert response.json()["reply"]["text"]


def test_station_generate_populates_tts_fields_when_provider_returns_audio(monkeypatch) -> None:
    client = TestClient(app)

    monkeypatch.setattr(
        station_tts,
        "build_tts_provider",
        lambda: _StubTtsProvider("/generated-audio/test.mp3"),
    )

    response = client.post("/api/station/generate", json=make_generate_payload())

    assert response.status_code == 200
    session = response.json()["session"]
    assert session["tts_audio_url"] == "/generated-audio/test.mp3"
    assert session["tts_text"]


def test_station_chat_updates_tts_fields_after_reply(monkeypatch) -> None:
    client = TestClient(app)
    payload = make_generate_payload()

    monkeypatch.setattr(
        station_tts,
        "build_tts_provider",
        lambda: _StubTtsProvider("/generated-audio/chat.mp3"),
    )

    generate_response = client.post("/api/station/generate", json=payload)
    assert generate_response.status_code == 200

    response = client.post(
        "/api/chat",
        json={
            "user_id": payload["user_id"],
            "message": "我想更安静一点，不要太满。",
            "device_context": payload["device_context"],
        },
    )

    assert response.status_code == 200
    state = get_station_session(payload["user_id"])
    assert state is not None
    assert state.session.tts_audio_url == "/generated-audio/chat.mp3"
    assert state.session.tts_text


def test_station_chat_like_control_records_feedback_and_memory_hint() -> None:
    client = TestClient(app)
    payload = make_generate_payload()
    generate_response = client.post("/api/station/generate", json=payload)

    assert generate_response.status_code == 200
    session = generate_response.json()["session"]
    current_item = session["playlist"]["items"][0]

    response = client.post(
        "/api/chat",
        json={
            "user_id": payload["user_id"],
            "message": "喜欢这首",
            "device_context": payload["device_context"],
        },
    )

    assert response.status_code == 200
    feedback_events = list_feedback_events(user_id=payload["user_id"])
    memory_hints = list_memory_update_hints(user_id=payload["user_id"])
    assert any(event.feedback_type.value == "like" for event in feedback_events)
    assert any(hint["action"] == "increase_affinity" for hint in memory_hints)
    assert any(event.candidate_id == current_item["candidate_id"] for event in feedback_events)


def test_station_chat_favorite_control_records_feedback_without_advancing_playlist() -> None:
    client = TestClient(app)
    payload = make_generate_payload()
    generate_response = client.post("/api/station/generate", json=payload)

    assert generate_response.status_code == 200
    session = generate_response.json()["session"]
    original_index = session["playlist"]["current_index"]
    current_item = session["playlist"]["items"][original_index]

    response = client.post(
        "/api/chat",
        json={
            "user_id": payload["user_id"],
            "message": "收藏这首",
            "device_context": payload["device_context"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["playlist"]["current_index"] == original_index
    feedback_events = list_feedback_events(user_id=payload["user_id"])
    memory_hints = list_memory_update_hints(user_id=payload["user_id"])
    assert any(event.feedback_type.value == "like" for event in feedback_events)
    assert any(event.candidate_id == current_item["candidate_id"] for event in feedback_events)
    assert any(hint["action"] == "increase_affinity" for hint in memory_hints)


def test_station_session_events_include_generate_and_chat_flow() -> None:
    client = TestClient(app)
    payload = make_generate_payload()

    generate_response = client.post("/api/station/generate", json=payload)

    assert generate_response.status_code == 200
    generated_session = generate_response.json()["session"]
    generate_event_types = {event["event_type"] for event in generated_session["events"]}
    assert "session_created" in generate_event_types

    chat_response = client.post(
        "/api/chat",
        json={
            "user_id": payload["user_id"],
            "message": "我想更安静一点，不要太满。",
            "device_context": payload["device_context"],
        },
    )

    assert chat_response.status_code == 200
    session = chat_response.json()["session"]
    event_types = {event["event_type"] for event in session["events"]}
    assert "reply_generated" in event_types
    assert "playlist_retuned" in event_types


def test_station_chat_control_events_include_feedback_and_playback_control() -> None:
    client = TestClient(app)
    payload = make_generate_payload()
    generate_response = client.post("/api/station/generate", json=payload)

    assert generate_response.status_code == 200

    response = client.post(
        "/api/chat",
        json={
            "user_id": payload["user_id"],
            "message": "跳过这首",
            "device_context": payload["device_context"],
        },
    )

    assert response.status_code == 200
    session = response.json()["session"]
    event_types = {event["event_type"] for event in session["events"]}
    assert "playback_control" in event_types
    assert "feedback_recorded" in event_types


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


class _StubTtsProvider:
    def __init__(self, audio_url: str) -> None:
        self._audio_url = audio_url

    def synthesize(self, text: str) -> tuple[str | None, str]:
        return self._audio_url, text.strip()
