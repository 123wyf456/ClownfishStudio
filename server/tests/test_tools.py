from datetime import UTC, datetime

import pytest

from app.core.config import get_settings
from app.schemas import (
    ContextSnapshot,
    FeedbackEvent,
    FeedbackType,
    ProgramBlock,
    ProgramItem,
    ProgramItemType,
    RadioProgram,
    UserStateInput,
)
from app.schemas.radio import DeviceContext
from app.tools import (
    build_memory_update_hint,
    get_netease_preference_candidates,
    get_program,
    get_recent_candidate_ids,
    get_recent_history,
    get_user_music_memory,
    get_weather,
    list_feedback_events,
    list_memory_update_hints,
    memory_tool,
    save_feedback,
    save_memory_update_hint,
    save_program,
    search_music_candidates,
    search_podcast_candidates,
)
from app.tools import netease_music_tool as netease_module
from app.tools.netease_music_tool import (
    _extract_playlist_genres,
    _get_json,
    _read_artists,
    search_netease_music_candidates,
)


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        del exc_type, exc, tb
        return False


def test_weather_tool_returns_city_weather_and_default_fallback() -> None:
    shanghai_weather = get_weather("Shanghai")
    unknown_weather = get_weather("Missing City")

    assert shanghai_weather["city"] == "Shanghai"
    assert shanghai_weather["source"] == "mock"
    assert unknown_weather["city"] == "Missing City"
    assert unknown_weather["condition"] == "clear"


def test_memory_tool_returns_existing_or_empty_memory() -> None:
    existing_memory = get_user_music_memory("demo-user")
    empty_memory = get_user_music_memory("new-user")

    assert "lofi" in existing_memory.favorite_genres
    assert empty_memory.user_id == "new-user"
    assert empty_memory.favorite_artists == []


def test_history_tool_returns_recent_candidate_ids() -> None:
    history = get_recent_history("demo-user", limit=2)
    candidate_ids = get_recent_candidate_ids("demo-user", limit=2)

    assert len(history) == 2
    assert candidate_ids == ["podcast-1", "music-2"]


def test_music_search_tool_reads_candidates_from_mock_json() -> None:
    candidates = search_music_candidates(tags=["lofi"], limit=5)

    assert [candidate.candidate_id for candidate in candidates] == ["music-2"]
    assert candidates[0].content_type == "music"


def test_music_search_reports_netease_failures_without_mock_fallback(monkeypatch) -> None:
    monkeypatch.setenv("NETEASE_API_BASE_URL", "http://127.0.0.1:9")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.tools.music_search_tool.search_netease_music_candidates",
        lambda **kwargs: (_ for _ in ()).throw(
            netease_module.NeteaseMusicToolError("NetEase API /search failed")
        ),
    )

    with pytest.raises(netease_module.NeteaseMusicToolError, match="/search"):
        search_music_candidates(query="Lamp", limit=5)


def test_netease_artist_parser_supports_search_payload_shape() -> None:
    artists = _read_artists({"artists": [{"name": "Artist A"}, {"name": "Artist B"}]})

    assert artists == ["Artist A", "Artist B"]


def test_netease_search_returns_empty_without_base_url() -> None:
    candidates = search_netease_music_candidates("Jay Chou", limit=2)

    assert isinstance(candidates, list)


def test_netease_playlist_genre_extraction_uses_api_tags_instead_of_hardcoded_mapping() -> None:
    genres = _extract_playlist_genres(
        {
            "tags": ["R&B/Soul", "City Pop"],
            "category": "夜晚",
        }
    )

    assert "r&b" in genres
    assert "soul" in genres
    assert "r&b/soul" in genres
    assert "city pop" in genres
    assert "夜晚" in genres


def test_memory_tool_merges_live_netease_memory(monkeypatch) -> None:
    monkeypatch.setattr(
        memory_tool,
        "get_netease_user_music_memory",
        lambda user_id: memory_tool.UserMusicMemory(
            user_id=user_id,
            favorite_genres=["r&b", "soul"],
            favorite_artists=["Brandy", "HYBS"],
            disliked_artists=[],
            recent_candidate_ids=[],
        ),
    )

    memory = get_user_music_memory("demo-user")

    assert "r&b" in memory.favorite_genres
    assert "Brandy" in memory.favorite_artists
    assert "Lamp" in memory.favorite_artists


def test_memory_tool_reports_netease_preference_failures(monkeypatch) -> None:
    monkeypatch.setenv("NETEASE_API_BASE_URL", "http://127.0.0.1:9")
    get_settings.cache_clear()
    monkeypatch.setattr(
        netease_module,
        "_get_preference_snapshot",
        lambda **kwargs: (_ for _ in ()).throw(
            netease_module.NeteaseMusicToolError("connection refused")
        ),
    )

    with pytest.raises(netease_module.NeteaseMusicToolError, match="connection refused"):
        get_user_music_memory("demo-user")


def test_netease_preference_candidates_returns_list_without_configuration() -> None:
    candidates = get_netease_preference_candidates(limit=2)

    assert isinstance(candidates, list)


def test_netease_candidate_tools_report_preference_failures(monkeypatch) -> None:
    monkeypatch.setenv("NETEASE_API_BASE_URL", "http://127.0.0.1:9")
    get_settings.cache_clear()
    monkeypatch.setattr(
        netease_module,
        "_get_preference_snapshot",
        lambda **kwargs: (_ for _ in ()).throw(
            netease_module.NeteaseMusicToolError("connection refused")
        ),
    )

    with pytest.raises(netease_module.NeteaseMusicToolError, match="connection refused"):
        get_netease_preference_candidates(limit=2)
    with pytest.raises(netease_module.NeteaseMusicToolError, match="connection refused"):
        netease_module.get_netease_personalized_candidates(limit=2)


def test_netease_json_requests_do_not_use_local_cache(monkeypatch) -> None:
    calls = {"count": 0}

    def fake_urlopen(request, timeout=15):  # noqa: ANN001
        del request, timeout
        calls["count"] += 1
        return FakeResponse(b'{"code":200,"data":{"ok":true}}')

    monkeypatch.setattr(netease_module, "urlopen", fake_urlopen)

    first = _get_json(
        base_url="http://localhost:3000",
        path="/login/status",
        params={},
        cookie="MUSIC_U=test-cookie",
    )
    second = _get_json(
        base_url="http://localhost:3000",
        path="/login/status",
        params={},
        cookie="MUSIC_U=test-cookie",
    )

    assert first == second
    assert calls["count"] == 2


def test_netease_search_requests_every_time(monkeypatch) -> None:
    calls = {"count": 0}

    def fake_urlopen(request, timeout=15):  # noqa: ANN001
        del request, timeout
        calls["count"] += 1
        return FakeResponse(b'{"code":200,"result":{"songs":[]}}')

    monkeypatch.setattr(netease_module, "urlopen", fake_urlopen)

    first = _get_json(
        base_url="http://localhost:3000",
        path="/search",
        params={"keywords": "Lamp", "limit": 4, "type": 1},
        cookie="MUSIC_U=test-cookie",
    )
    second = _get_json(
        base_url="http://localhost:3000",
        path="/search",
        params={"keywords": "Lamp", "limit": 4, "type": 1},
        cookie="MUSIC_U=test-cookie",
    )

    assert first == second
    assert calls["count"] == 2


def test_podcast_search_tool_reads_candidates_from_mock_json() -> None:
    candidates = search_podcast_candidates(query="familiar", limit=5)

    assert [candidate.candidate_id for candidate in candidates] == ["podcast-2"]
    assert candidates[0].content_type == "podcast"


def test_program_tool_saves_and_reads_programs() -> None:
    program = make_program(program_id="program-tool-test")

    saved_program = save_program(program)

    assert saved_program.program_id == "program-tool-test"
    assert get_program("program-tool-test") == program


def test_feedback_tool_saves_feedback_and_builds_memory_hint() -> None:
    feedback = FeedbackEvent(
        feedback_type=FeedbackType.too_familiar,
        user_id="tool-test-user",
        program_id="program-tool-test",
        candidate_id="music-1",
    )

    saved_feedback = save_feedback(feedback)
    hint = build_memory_update_hint(feedback)
    save_memory_update_hint(hint)

    assert saved_feedback in list_feedback_events(user_id="tool-test-user")
    assert hint in list_memory_update_hints(user_id="tool-test-user")
    assert hint["action"] == "reduce_repetition"
    assert hint["candidate_id"] == "music-1"


def make_program(program_id: str) -> RadioProgram:
    device_context = DeviceContext(
        local_time=datetime(2026, 4, 30, 22, 30, tzinfo=UTC),
        timezone="Asia/Shanghai",
        city_hint="Shanghai",
    )
    user_state = UserStateInput(duration_minutes=20, free_text="Need something lighter tonight.")
    context_snapshot = ContextSnapshot(
        device_context=device_context,
        user_state=user_state,
        weather=get_weather("Shanghai"),
    )

    return RadioProgram(
        program_id=program_id,
        title="Mock Program",
        summary="A saved mock radio program.",
        context_snapshot=context_snapshot,
        total_duration_minutes=20,
        blocks=[
            ProgramBlock(
                block_id="block-1",
                title="Mock Block",
                position=0,
                items=[
                    ProgramItem(
                        item_id="item-1",
                        item_type=ProgramItemType.narration,
                        title="Opening",
                        position=0,
                        narration_text="Welcome back.",
                    )
                ],
            )
        ],
    )
