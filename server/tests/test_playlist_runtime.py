from app.schemas import (
    CandidateItem,
    ContentType,
    PlayerAdvanceReason,
    PlaylistRecommendationKind,
)
from app.services.playlist_runtime import (
    advance_playlist,
    create_playlist_from_candidates,
    refill_playlist,
    remaining_count,
    retune_playlist_after_current,
)


def test_retune_replaces_upcoming_items_one_by_one_and_records_dropped_items() -> None:
    playlist = create_playlist_from_candidates(make_candidates("old", 8))
    playlist = playlist.model_copy(update={"current_index": 2})

    mutation = retune_playlist_after_current(playlist, make_candidates("new", 3))

    assert mutation.playlist.current_index == 0
    assert [item.candidate_id for item in mutation.dropped_items] == [
        "old-0",
        "old-1",
        "old-3",
        "old-4",
        "old-5",
    ]
    assert [item.candidate_id for item in mutation.playlist.items] == [
        "old-2",
        "new-0",
        "new-1",
        "new-2",
        "old-6",
        "old-7",
    ]
    assert mutation.warnings == [
        "Only part of the upcoming playlist was replaced; the remaining songs were kept."
    ]


def test_refill_keeps_current_and_recent_previous_items_when_window_is_full() -> None:
    playlist = create_playlist_from_candidates(make_candidates("old", 8))
    playlist = playlist.model_copy(update={"current_index": 4})

    mutation = refill_playlist(playlist, make_candidates("new", 4))

    assert mutation.playlist.current_index == 2
    assert remaining_count(mutation.playlist) == 5
    assert [item.candidate_id for item in mutation.dropped_items] == ["old-0", "old-1"]
    assert [item.candidate_id for item in mutation.playlist.items] == [
        "old-2",
        "old-3",
        "old-4",
        "old-5",
        "old-6",
        "old-7",
        "new-0",
        "new-1",
    ]


def test_advance_playlist_keeps_items_and_moves_current_index() -> None:
    playlist = create_playlist_from_candidates(make_candidates("old", 4))

    advanced = advance_playlist(playlist, reason=PlayerAdvanceReason.ended)
    previous = advance_playlist(advanced, reason=PlayerAdvanceReason.previous)

    assert len(advanced.items) == 4
    assert advanced.current_index == 1
    assert previous.current_index == 0


def test_playlist_item_marks_mock_fallback_source() -> None:
    playlist = create_playlist_from_candidates(
        [
            CandidateItem(
                candidate_id="mock-1",
                content_type=ContentType.music,
                title="Mock Song",
                creator="Mock Artist",
                duration_seconds=180,
                playback_url="mock://audio/mock-1",
                tags=["fallback_search"],
                source="mock_music",
            )
        ]
    )

    item = playlist.items[0]
    assert item.recommendation_kind is PlaylistRecommendationKind.mock_fallback
    assert item.source == "mock_music"
    assert item.tags == ["fallback_search"]


def test_playlist_item_marks_netease_preference_recommendation() -> None:
    playlist = create_playlist_from_candidates(
        [
            CandidateItem(
                candidate_id="netease-1",
                content_type=ContentType.music,
                title="Real Favorite",
                creator="Known Artist",
                duration_seconds=180,
                playback_url="https://example.com/real.mp3",
                tags=["netease", "real_playback", "user_preference"],
                source="netease_cloud_music",
                metadata={"preference_source": "liked_playlist"},
            )
        ]
    )

    item = playlist.items[0]
    assert item.recommendation_kind is PlaylistRecommendationKind.real_recommendation
    assert item.metadata["preference_source"] == "liked_playlist"


def test_playlist_item_marks_netease_search_result() -> None:
    playlist = create_playlist_from_candidates(
        [
            CandidateItem(
                candidate_id="netease-2",
                content_type=ContentType.music,
                title="Real Search",
                creator="Search Artist",
                duration_seconds=180,
                playback_url="https://example.com/search.mp3",
                tags=["netease", "real_playback", "search_result"],
                source="netease_cloud_music",
            )
        ]
    )

    assert playlist.items[0].recommendation_kind is PlaylistRecommendationKind.real_search


def make_candidates(prefix: str, count: int) -> list[CandidateItem]:
    return [
        CandidateItem(
            candidate_id=f"{prefix}-{index}",
            content_type=ContentType.music,
            title=f"{prefix.title()} Song {index}",
            creator=f"{prefix.title()} Artist",
            duration_seconds=180,
            playback_url=f"https://example.com/{prefix}-{index}.mp3",
            tags=[],
            source="test",
        )
        for index in range(count)
    ]
