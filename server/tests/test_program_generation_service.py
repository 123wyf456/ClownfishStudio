from datetime import UTC, datetime

from app.agents import AgentOutputValidationError
from app.agents.song_request_agent import SongRequestPlan
from app.schemas import (
    CandidateItem,
    ChatMessage,
    ContentType,
    DeviceContext,
    GenerateProgramRequest,
    UserStateInput,
)
from app.services.program_generation import ProgramGenerationService


def test_collect_candidates_uses_free_text_for_targeted_music(monkeypatch) -> None:
    captured_queries: list[str | None] = []
    targeted_candidate = CandidateItem(
        candidate_id="netease-target",
        content_type=ContentType.music,
        title="Targeted Song",
        creator="Artist",
        duration_seconds=180,
        playback_url="https://example.com/song.mp3",
        tags=["user_preference"],
        source="netease_cloud_music",
    )

    def fake_search_music_candidates(
        query: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> list[CandidateItem]:
        del tags, limit
        captured_queries.append(query)
        if query == "Brandy":
            return [targeted_candidate]
        return []

    monkeypatch.setattr(
        "app.services.program_generation.get_netease_preference_candidates",
        lambda limit=8: [],
    )
    monkeypatch.setattr(
        "app.services.program_generation.search_music_candidates",
        fake_search_music_candidates,
    )
    monkeypatch.setattr(
        "app.services.program_generation.search_podcast_candidates",
        lambda query=None, tags=None, limit=10: [],
    )

    service = ProgramGenerationService(song_request_planner=_GeneralSongRequestPlanner())
    request = GenerateProgramRequest(
        user_id="demo-user",
        device_context=DeviceContext(
            local_time=datetime(2026, 4, 30, 22, 30, tzinfo=UTC),
            timezone="Asia/Shanghai",
            city_hint="Shanghai",
        ),
        user_state=UserStateInput(duration_minutes=25, free_text="Brandy"),
        max_candidates=6,
    )

    candidate_items, warnings = service._collect_candidates(request)

    assert captured_queries[0] == "Brandy"
    assert candidate_items[0].candidate_id == "netease-target"
    assert warnings == []


def test_collect_candidates_does_not_search_raw_user_sentence(monkeypatch) -> None:
    captured_queries: list[str | None] = []
    targeted_candidate = CandidateItem(
        candidate_id="netease-weeknd",
        content_type=ContentType.music,
        title="Blinding Lights",
        creator="The Weeknd",
        duration_seconds=200,
        playback_url="https://example.com/weeknd.mp3",
        tags=["search_result"],
        source="netease_cloud_music",
    )

    def fake_search_music_candidates(
        query: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> list[CandidateItem]:
        del tags, limit
        captured_queries.append(query)
        return [targeted_candidate] if query and "weeknd" in query.lower() else []

    monkeypatch.setattr(
        "app.services.program_generation.get_netease_preference_candidates",
        lambda limit=8: [],
    )
    monkeypatch.setattr(
        "app.services.program_generation.get_netease_personalized_candidates",
        lambda limit=8: [],
    )
    monkeypatch.setattr(
        "app.services.program_generation.search_music_candidates",
        fake_search_music_candidates,
    )
    monkeypatch.setattr(
        "app.services.program_generation.search_podcast_candidates",
        lambda query=None, tags=None, limit=10: [],
    )

    service = ProgramGenerationService(song_request_planner=_GeneralSongRequestPlanner())
    service._song_request_planner = _MessySongRequestPlanner()
    request = GenerateProgramRequest(
        user_id="demo-user",
        device_context=DeviceContext(
            local_time=datetime(2026, 4, 30, 22, 30, tzinfo=UTC),
            timezone="Asia/Shanghai",
            city_hint="Shanghai",
        ),
        user_state=UserStateInput(
            duration_minutes=25,
            free_text="放一些轻松的歌 推荐weeknd的歌",
            needs=["companionship"],
        ),
        max_candidates=8,
    )

    candidate_items, warnings = service._collect_candidates(request)

    assert candidate_items
    assert warnings == []
    assert "放一些轻松的歌 推荐weeknd的歌" not in captured_queries
    assert all("companionship" not in str(query).lower() for query in captured_queries)
    assert all("unknown" not in str(query).lower() for query in captured_queries)


def test_collect_candidates_uses_contextual_query_for_auto_boot(monkeypatch) -> None:
    captured_queries: list[str | None] = []

    def fake_search_music_candidates(
        query: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> list[CandidateItem]:
        del tags, limit
        captured_queries.append(query)
        return []

    monkeypatch.setattr(
        "app.services.program_generation.get_netease_preference_candidates",
        lambda limit=8: [],
    )
    monkeypatch.setattr(
        "app.services.program_generation.get_netease_personalized_candidates",
        lambda limit=8: [],
    )
    monkeypatch.setattr(
        "app.services.program_generation.search_music_candidates",
        fake_search_music_candidates,
    )
    monkeypatch.setattr(
        "app.services.program_generation.search_podcast_candidates",
        lambda query=None, tags=None, limit=10: [],
    )

    service = ProgramGenerationService(song_request_planner=_GeneralSongRequestPlanner())
    request = GenerateProgramRequest(
        user_id="demo-user",
        device_context=DeviceContext(
            local_time=datetime(2026, 4, 30, 22, 30, tzinfo=UTC),
            timezone="Asia/Shanghai",
            city_hint="Shanghai",
        ),
        user_state=UserStateInput(
            duration_minutes=25,
            needs=["companionship"],
            free_text="启动 ClownfishStudio。简单打招呼并自我介绍，然后开始此刻的电台。",
        ),
        max_candidates=8,
    )

    service._collect_candidates(request)

    assert captured_queries
    assert all("clownfish" not in str(query).lower() for query in captured_queries)
    assert all("打招呼" not in str(query) for query in captured_queries)
    assert any(query and "late night" in query.lower() for query in captured_queries)


def test_collect_candidates_stops_searching_after_enough_targeted_batch(
    monkeypatch,
) -> None:
    captured_queries: list[str | None] = []
    batch = [
        CandidateItem(
            candidate_id=f"netease-weeknd-{index}",
            content_type=ContentType.music,
            title=f"Weeknd Song {index}",
            creator="The Weeknd",
            duration_seconds=200,
            playback_url=f"https://example.com/weeknd-{index}.mp3",
            tags=["search_result"],
            source="netease_cloud_music",
        )
        for index in range(4)
    ]

    def fake_search_music_candidates(
        query: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> list[CandidateItem]:
        del tags, limit
        captured_queries.append(query)
        return batch if query == "The Weeknd" else []

    monkeypatch.setattr(
        "app.services.program_generation.get_netease_preference_candidates",
        lambda limit=8: [],
    )
    monkeypatch.setattr(
        "app.services.program_generation.get_netease_personalized_candidates",
        lambda limit=8: [],
    )
    monkeypatch.setattr(
        "app.services.program_generation.search_music_candidates",
        fake_search_music_candidates,
    )
    monkeypatch.setattr(
        "app.services.program_generation.search_podcast_candidates",
        lambda query=None, tags=None, limit=10: [],
    )

    service = ProgramGenerationService(song_request_planner=_GeneralSongRequestPlanner())
    service._song_request_planner = _WeekndArtistSongRequestPlanner()
    request = GenerateProgramRequest(
        user_id="demo-user",
        device_context=DeviceContext(
            local_time=datetime(2026, 4, 30, 22, 30, tzinfo=UTC),
            timezone="Asia/Shanghai",
            city_hint="Shanghai",
        ),
        user_state=UserStateInput(duration_minutes=25, free_text="推荐 The Weeknd 的歌"),
        max_candidates=8,
    )

    candidate_items, warnings = service._collect_candidates(request)

    assert len(candidate_items) == 4
    assert warnings == []
    assert captured_queries == ["The Weeknd"]


def test_collect_candidates_warns_once_when_targeted_music_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.program_generation.get_netease_preference_candidates",
        lambda limit=8: [],
    )
    monkeypatch.setattr(
        "app.services.program_generation.search_music_candidates",
        lambda query=None, tags=None, limit=10: [],
    )
    monkeypatch.setattr(
        "app.services.program_generation.search_podcast_candidates",
        lambda query=None, tags=None, limit=10: [],
    )

    service = ProgramGenerationService(song_request_planner=_GeneralSongRequestPlanner())
    request = GenerateProgramRequest(
        user_id="demo-user",
        device_context=DeviceContext(
            local_time=datetime(2026, 4, 30, 22, 30, tzinfo=UTC),
            timezone="Asia/Shanghai",
            city_hint="Shanghai",
        ),
        user_state=UserStateInput(duration_minutes=25, free_text="night drive"),
        max_candidates=6,
    )

    _, warnings = service._collect_candidates(request)

    assert warnings[0] == (
        "No personalized or targeted music candidates matched; used fallback results."
    )


def test_collect_candidates_uses_broad_fallback_after_empty_targeted_searches(monkeypatch) -> None:
    captured_queries: list[str | None] = []
    broad_candidate = CandidateItem(
        candidate_id="music-broad",
        content_type=ContentType.music,
        title="Broad Song",
        creator="Fallback Artist",
        duration_seconds=180,
        playback_url="https://example.com/broad.mp3",
        tags=["night"],
        source="mock_music",
    )

    def fake_search_music_candidates(
        query: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> list[CandidateItem]:
        del tags, limit
        captured_queries.append(query)
        return [broad_candidate] if query == "Lamp" else []

    monkeypatch.setattr(
        "app.services.program_generation.get_netease_preference_candidates",
        lambda limit=8: [],
    )
    monkeypatch.setattr(
        "app.services.program_generation.get_netease_personalized_candidates",
        lambda limit=8: [],
    )
    monkeypatch.setattr(
        "app.services.program_generation.search_music_candidates",
        fake_search_music_candidates,
    )
    monkeypatch.setattr(
        "app.services.program_generation.search_podcast_candidates",
        lambda query=None, tags=None, limit=10: [],
    )

    service = ProgramGenerationService(song_request_planner=_GeneralSongRequestPlanner())
    request = GenerateProgramRequest(
        user_id="demo-user",
        device_context=DeviceContext(
            local_time=datetime(2026, 4, 30, 22, 30, tzinfo=UTC),
            timezone="Asia/Shanghai",
            city_hint="Shanghai",
        ),
        user_state=UserStateInput(duration_minutes=25, free_text="unmatched phrase"),
        max_candidates=6,
    )

    candidate_items, warnings = service._collect_candidates(request)

    assert candidate_items[0].candidate_id == "music-broad"
    assert "Lamp" in captured_queries
    assert warnings == [
        "No personalized or targeted music candidates matched; used fallback results."
    ]


def test_collect_candidates_uses_non_raw_broad_fallback_for_mood_mix(monkeypatch) -> None:
    captured_queries: list[str | None] = []
    broad_candidate = CandidateItem(
        candidate_id="music-mood-broad",
        content_type=ContentType.music,
        title="Mood Broad Song",
        creator="Fallback Artist",
        duration_seconds=180,
        playback_url="https://example.com/mood-broad.mp3",
        tags=["quiet"],
        source="mock_music",
    )

    def fake_search_music_candidates(
        query: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> list[CandidateItem]:
        del tags, limit
        captured_queries.append(query)
        return [broad_candidate] if query == "Lamp" else []

    monkeypatch.setattr(
        "app.services.program_generation.get_netease_preference_candidates",
        lambda limit=8: [],
    )
    monkeypatch.setattr(
        "app.services.program_generation.get_netease_personalized_candidates",
        lambda limit=8: [],
    )
    monkeypatch.setattr(
        "app.services.program_generation.search_music_candidates",
        fake_search_music_candidates,
    )
    monkeypatch.setattr(
        "app.services.program_generation.search_podcast_candidates",
        lambda query=None, tags=None, limit=10: [],
    )

    service = ProgramGenerationService(song_request_planner=_GeneralSongRequestPlanner())
    service._song_request_planner = _MoodMixSongRequestPlanner()
    request = GenerateProgramRequest(
        user_id="demo-user",
        device_context=DeviceContext(
            local_time=datetime(2026, 4, 30, 22, 30, tzinfo=UTC),
            timezone="Asia/Shanghai",
            city_hint="Shanghai",
        ),
        user_state=UserStateInput(
            duration_minutes=25,
            free_text="I feel tired and want something lighter",
        ),
        max_candidates=6,
    )

    candidate_items, warnings = service._collect_candidates(request)

    assert candidate_items[0].candidate_id == "music-mood-broad"
    assert "Lamp" in captured_queries
    assert request.user_state.free_text not in captured_queries
    assert warnings == [
        "No personalized or targeted music candidates matched; used fallback results."
    ]


def test_collect_candidates_prioritizes_song_request_plan_matches(monkeypatch) -> None:
    exact_candidate = CandidateItem(
        candidate_id="netease-exact",
        content_type=ContentType.music,
        title="Almost",
        creator="Tamia",
        duration_seconds=240,
        playback_url="https://example.com/exact.mp3",
        tags=["search_result", "query_match"],
        source="netease_cloud_music",
        metadata={"search_query": "Almost Tamia"},
    )
    preference_candidate = CandidateItem(
        candidate_id="netease-preference",
        content_type=ContentType.music,
        title="Fallback Favorite",
        creator="Known Artist",
        duration_seconds=220,
        playback_url="https://example.com/preference.mp3",
        tags=["user_preference", "recent_favorite"],
        source="netease_cloud_music",
    )

    monkeypatch.setattr(
        "app.services.program_generation.get_netease_preference_candidates",
        lambda limit=8: [preference_candidate],
    )
    monkeypatch.setattr(
        "app.services.program_generation.get_netease_personalized_candidates",
        lambda limit=8: [],
    )
    monkeypatch.setattr(
        "app.services.program_generation.search_music_candidates",
        lambda query=None, tags=None, limit=10: (
            [exact_candidate] if query and "Almost" in query else []
        ),
    )
    monkeypatch.setattr(
        "app.services.program_generation.search_podcast_candidates",
        lambda query=None, tags=None, limit=10: [],
    )

    service = ProgramGenerationService(song_request_planner=_GeneralSongRequestPlanner())
    service._song_request_planner = _StubSongRequestPlanner()
    request = GenerateProgramRequest(
        user_id="demo-user",
        device_context=DeviceContext(
            local_time=datetime(2026, 4, 30, 22, 30, tzinfo=UTC),
            timezone="Asia/Shanghai",
            city_hint="Shanghai",
        ),
        user_state=UserStateInput(duration_minutes=25, free_text="播放 Almost by Tamia"),
        max_candidates=6,
    )

    candidate_items, warnings = service._collect_candidates(request)

    assert warnings == []
    assert candidate_items[0].candidate_id == "netease-exact"


def test_collect_candidates_filters_to_requested_artist_when_artist_focus(monkeypatch) -> None:
    exact_artist = CandidateItem(
        candidate_id="netease-jj-1",
        content_type=ContentType.music,
        title="江南",
        creator="林俊杰",
        duration_seconds=230,
        playback_url="https://example.com/jj.mp3",
        tags=["search_result", "query_match"],
        source="netease_cloud_music",
    )
    wrong_artist = CandidateItem(
        candidate_id="netease-other-1",
        content_type=ContentType.music,
        title="Unrelated Song",
        creator="Other Artist",
        duration_seconds=210,
        playback_url="https://example.com/other.mp3",
        tags=["search_result", "query_match"],
        source="netease_cloud_music",
    )

    monkeypatch.setattr(
        "app.services.program_generation.get_netease_preference_candidates",
        lambda limit=8: [],
    )
    monkeypatch.setattr(
        "app.services.program_generation.get_netease_personalized_candidates",
        lambda limit=8: [],
    )
    monkeypatch.setattr(
        "app.services.program_generation.search_music_candidates",
        lambda query=None, tags=None, limit=10: [exact_artist, wrong_artist],
    )
    monkeypatch.setattr(
        "app.services.program_generation.search_podcast_candidates",
        lambda query=None, tags=None, limit=10: [],
    )

    service = ProgramGenerationService(song_request_planner=_GeneralSongRequestPlanner())
    service._song_request_planner = _ArtistFocusSongRequestPlanner()
    request = GenerateProgramRequest(
        user_id="demo-user",
        device_context=DeviceContext(
            local_time=datetime(2026, 4, 30, 22, 30, tzinfo=UTC),
            timezone="Asia/Shanghai",
            city_hint="Shanghai",
        ),
        user_state=UserStateInput(duration_minutes=25, free_text="推荐林俊杰的歌"),
        max_candidates=8,
    )

    candidate_items, warnings = service._collect_candidates(request)

    assert warnings == []
    assert candidate_items
    assert all(candidate.creator == "林俊杰" for candidate in candidate_items)


def test_collect_candidates_does_not_fill_artist_focus_with_unrelated_tracks(
    monkeypatch,
) -> None:
    wrong_artist = CandidateItem(
        candidate_id="netease-other-1",
        content_type=ContentType.music,
        title="Unrelated Song",
        creator="Other Artist",
        duration_seconds=210,
        playback_url="https://example.com/other.mp3",
        tags=["search_result", "query_match"],
        source="netease_cloud_music",
    )
    broad_fallback = CandidateItem(
        candidate_id="music-broad",
        content_type=ContentType.music,
        title="Broad Song",
        creator="Fallback Artist",
        duration_seconds=180,
        playback_url="https://example.com/broad.mp3",
        tags=["night"],
        source="mock_music",
    )

    monkeypatch.setattr(
        "app.services.program_generation.get_netease_preference_candidates",
        lambda limit=8: [],
    )
    monkeypatch.setattr(
        "app.services.program_generation.get_netease_personalized_candidates",
        lambda limit=8: [],
    )
    monkeypatch.setattr(
        "app.services.program_generation.search_music_candidates",
        lambda query=None, tags=None, limit=10: (
            [broad_fallback] if query is None else [wrong_artist]
        ),
    )
    monkeypatch.setattr(
        "app.services.program_generation.search_podcast_candidates",
        lambda query=None, tags=None, limit=10: [],
    )

    service = ProgramGenerationService(song_request_planner=_GeneralSongRequestPlanner())
    service._song_request_planner = _ArtistFocusSongRequestPlanner()
    request = GenerateProgramRequest(
        user_id="demo-user",
        device_context=DeviceContext(
            local_time=datetime(2026, 4, 30, 22, 30, tzinfo=UTC),
            timezone="Asia/Shanghai",
            city_hint="Shanghai",
        ),
        user_state=UserStateInput(duration_minutes=25, free_text="推荐林俊杰的歌"),
        max_candidates=8,
    )

    candidate_items, warnings = service._collect_candidates(request)

    assert candidate_items == []
    assert warnings == [
        "No music candidates matched the requested song or artist; "
        "no unrelated fallback tracks were added.",
        "No candidate content is available; radio generation cannot continue.",
    ]


def test_collect_candidates_passes_context_to_song_request_planner(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "app.services.program_generation.get_netease_preference_candidates",
        lambda limit=8: [],
    )
    monkeypatch.setattr(
        "app.services.program_generation.get_netease_personalized_candidates",
        lambda limit=8: [],
    )
    monkeypatch.setattr(
        "app.services.program_generation.search_music_candidates",
        lambda query=None, tags=None, limit=10: [],
    )
    monkeypatch.setattr(
        "app.services.program_generation.search_podcast_candidates",
        lambda query=None, tags=None, limit=10: [],
    )

    service = ProgramGenerationService(song_request_planner=_GeneralSongRequestPlanner())
    service._song_request_planner = _CapturingSongRequestPlanner(captured)
    request = GenerateProgramRequest(
        user_id="demo-user",
        device_context=DeviceContext(
            local_time=datetime(2026, 4, 30, 22, 30, tzinfo=UTC),
            timezone="Asia/Shanghai",
            city_hint="Shanghai",
        ),
        user_state=UserStateInput(duration_minutes=25, free_text="今晚想安静一点"),
        max_candidates=6,
    )

    chat_history = [ChatMessage(role="user", text="上一轮说想安静一点")]
    service._collect_candidates(request, chat_history=chat_history)

    assert captured["device_context"] == request.device_context
    assert captured["user_state"] == request.user_state
    assert isinstance(captured["history"], list)
    assert captured["chat_history"] == chat_history


def test_collect_candidates_raises_when_song_request_planner_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.program_generation.get_netease_preference_candidates",
        lambda limit=8: [],
    )
    monkeypatch.setattr(
        "app.services.program_generation.get_netease_personalized_candidates",
        lambda limit=8: [],
    )
    monkeypatch.setattr(
        "app.services.program_generation.search_music_candidates",
        lambda query=None, tags=None, limit=10: [],
    )
    monkeypatch.setattr(
        "app.services.program_generation.search_podcast_candidates",
        lambda query=None, tags=None, limit=10: [],
    )

    service = ProgramGenerationService(song_request_planner=_GeneralSongRequestPlanner())
    service._song_request_planner = _FailingSongRequestPlanner()
    request = GenerateProgramRequest(
        user_id="demo-user",
        device_context=DeviceContext(
            local_time=datetime(2026, 4, 30, 22, 30, tzinfo=UTC),
            timezone="Asia/Shanghai",
            city_hint="Shanghai",
        ),
        user_state=UserStateInput(duration_minutes=25, free_text="quiet night"),
        max_candidates=6,
    )

    try:
        service._collect_candidates(request)
    except AgentOutputValidationError as exc:
        assert "Song request agent failed" in str(exc)
    else:
        raise AssertionError("planner failures must not fall back to local request planning")


class _GeneralSongRequestPlanner:
    def plan(self, *, message: str, memory, weather, **kwargs) -> SongRequestPlan:  # noqa: ANN001
        del memory, weather, kwargs
        is_auto_boot = "ClownfishStudio" in message or "此刻的电台" in message
        return SongRequestPlan(
            intent=message or "general radio",
            search_queries=["late night"] if is_auto_boot or not message else [message],
            preferred_title=None,
            preferred_artist=None,
            preferred_tags=["late night"] if is_auto_boot or not message else [],
            mode="mood_mix" if is_auto_boot or not message else "general",
            reason="test double",
        )


class _StubSongRequestPlanner:
    def plan(self, *, message: str, memory, weather, **kwargs) -> SongRequestPlan:  # noqa: ANN001
        del message, memory, weather, kwargs
        return SongRequestPlan(
            intent="play Almost by Tamia",
            search_queries=["Almost Tamia"],
            preferred_title="Almost",
            preferred_artist="Tamia",
            preferred_tags=["r&b"],
            mode="precise_song",
            reason="stub",
        )


class _MessySongRequestPlanner:
    def plan(self, *, message: str, memory, weather, **kwargs) -> SongRequestPlan:  # noqa: ANN001
        del message, memory, weather, kwargs
        return SongRequestPlan(
            intent="recommend relaxed Weeknd songs",
            search_queries=[
                "放一些轻松的歌 推荐",
                "rnb 放一些轻松的歌 推荐weeknd的歌 companionship unknown",
                "rnb weeknd",
            ],
            preferred_title=None,
            preferred_artist="The Weeknd",
            preferred_tags=["rnb", "轻松"],
            mode="artist_focus",
            reason="stub",
        )


class _WeekndArtistSongRequestPlanner:
    def plan(self, *, message: str, memory, weather, **kwargs) -> SongRequestPlan:  # noqa: ANN001
        del message, memory, weather, kwargs
        return SongRequestPlan(
            intent="recommend The Weeknd songs",
            search_queries=["The Weeknd", "rnb weeknd", "weeknd hits"],
            preferred_title=None,
            preferred_artist="The Weeknd",
            preferred_tags=["r&b"],
            mode="artist_focus",
            reason="stub",
        )


class _ArtistFocusSongRequestPlanner:
    def plan(self, *, message: str, memory, weather, **kwargs) -> SongRequestPlan:  # noqa: ANN001
        del message, memory, weather, kwargs
        return SongRequestPlan(
            intent="推荐林俊杰的歌",
            search_queries=["林俊杰"],
            preferred_title=None,
            preferred_artist="林俊杰",
            preferred_tags=["深夜"],
            mode="artist_focus",
            reason="stub",
        )


class _CapturingSongRequestPlanner:
    def __init__(self, captured: dict[str, object]) -> None:
        self._captured = captured

    def plan(self, *, message: str, memory, weather, **kwargs) -> SongRequestPlan:  # noqa: ANN001
        del message, memory, weather
        self._captured.update(kwargs)
        return SongRequestPlan(
            intent="quiet night",
            search_queries=["quiet night"],
            preferred_title=None,
            preferred_artist=None,
            preferred_tags=["quiet"],
            mode="mood_mix",
            reason="stub",
        )


class _MoodMixSongRequestPlanner:
    def plan(self, *, message: str, memory, weather, **kwargs) -> SongRequestPlan:  # noqa: ANN001
        del message, memory, weather, kwargs
        return SongRequestPlan(
            intent="quiet mood",
            search_queries=["quiet night"],
            preferred_title=None,
            preferred_artist=None,
            preferred_tags=["quiet"],
            mode="mood_mix",
            reason="stub",
        )


class _FailingSongRequestPlanner:
    def plan(self, **kwargs) -> SongRequestPlan:  # noqa: ANN003
        del kwargs
        raise ValueError("empty model response")
