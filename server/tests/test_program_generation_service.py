from datetime import UTC, datetime

from app.agents.song_request_agent import SongRequestPlan
from app.schemas import (
    CandidateItem,
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

    service = ProgramGenerationService()
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

    service = ProgramGenerationService()
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
        return [broad_candidate] if query is None else []

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

    service = ProgramGenerationService()
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
        lambda query=None, tags=None, limit=10: [exact_candidate]
        if query and "Almost" in query
        else [],
    )
    monkeypatch.setattr(
        "app.services.program_generation.search_podcast_candidates",
        lambda query=None, tags=None, limit=10: [],
    )

    service = ProgramGenerationService()
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
        title="夜曲",
        creator="周杰伦",
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

    service = ProgramGenerationService()
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


class _StubSongRequestPlanner:
    def plan(self, *, message: str, memory, weather) -> SongRequestPlan:  # noqa: ANN001
        del message, memory, weather
        return SongRequestPlan(
            intent="play Almost by Tamia",
            search_queries=["Almost Tamia"],
            preferred_title="Almost",
            preferred_artist="Tamia",
            preferred_tags=["r&b"],
            mode="precise_song",
            reason="stub",
        )


class _ArtistFocusSongRequestPlanner:
    def plan(self, *, message: str, memory, weather) -> SongRequestPlan:  # noqa: ANN001
        del message, memory, weather
        return SongRequestPlan(
            intent="推荐林俊杰的歌",
            search_queries=["林俊杰"],
            preferred_title=None,
            preferred_artist="林俊杰",
            preferred_tags=["深夜"],
            mode="artist_focus",
            reason="stub",
        )

