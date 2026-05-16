from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from app.schemas import (
    CandidateItem,
    ContentType,
    PlayerAdvanceReason,
    PlaylistItem,
    PlaylistItemSource,
    PlaylistRecommendationKind,
    RadioPlaylist,
)
from app.tools import save_history_event

DEFAULT_TARGET_SIZE = 8
DEFAULT_REFILL_THRESHOLD = 3
DEFAULT_PREVIOUS_KEEP = 2


@dataclass(frozen=True)
class PlaylistMutationResult:
    playlist: RadioPlaylist
    dropped_items: list[PlaylistItem] = field(default_factory=list)
    inserted_items: list[PlaylistItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def create_playlist_from_candidates(
    candidates: list[CandidateItem],
    *,
    inserted_by: PlaylistItemSource = PlaylistItemSource.initial,
    target_size: int = DEFAULT_TARGET_SIZE,
    refill_threshold: int = DEFAULT_REFILL_THRESHOLD,
) -> RadioPlaylist:
    items = _playlist_items_from_candidates(
        candidates,
        inserted_by=inserted_by,
        limit=target_size,
        existing_candidate_ids=set(),
    )
    return RadioPlaylist(
        playlist_id=f"playlist-{uuid4().hex}",
        items=items,
        current_index=0,
        target_size=target_size,
        refill_threshold=refill_threshold,
        revision=0,
        updated_at=datetime.now(UTC),
    )


def advance_playlist(
    playlist: RadioPlaylist,
    *,
    reason: PlayerAdvanceReason,
) -> RadioPlaylist:
    if not playlist.items:
        return playlist

    next_index = playlist.current_index
    if reason is PlayerAdvanceReason.previous:
        next_index = max(0, playlist.current_index - 1)
    else:
        next_index = min(len(playlist.items) - 1, playlist.current_index + 1)

    if next_index == playlist.current_index:
        return playlist

    return playlist.model_copy(
        update={
            "current_index": next_index,
            "revision": playlist.revision + 1,
            "updated_at": datetime.now(UTC),
        }
    )


def playlist_needs_refill(playlist: RadioPlaylist) -> bool:
    return remaining_count(playlist) <= playlist.refill_threshold


def remaining_count(playlist: RadioPlaylist) -> int:
    if not playlist.items:
        return 0
    return max(0, len(playlist.items) - playlist.current_index - 1)


def refill_playlist(
    playlist: RadioPlaylist,
    candidates: list[CandidateItem],
) -> PlaylistMutationResult:
    if not playlist.items:
        return PlaylistMutationResult(
            playlist=create_playlist_from_candidates(
                candidates,
                inserted_by=PlaylistItemSource.refill,
                target_size=playlist.target_size,
                refill_threshold=playlist.refill_threshold,
            )
        )

    previous_keep = min(playlist.current_index, DEFAULT_PREVIOUS_KEEP)
    keep_start = max(0, playlist.current_index - previous_keep)
    kept_items = playlist.items[keep_start:]
    dropped_items = playlist.items[:keep_start]
    slots = max(0, playlist.target_size - len(kept_items))
    if slots <= 0:
        normalized_playlist = playlist.model_copy(
            update={
                "items": kept_items[: playlist.target_size],
                "current_index": previous_keep,
                "revision": playlist.revision + (1 if dropped_items else 0),
                "updated_at": datetime.now(UTC),
            }
        )
        return PlaylistMutationResult(playlist=normalized_playlist, dropped_items=dropped_items)

    existing_candidate_ids = {item.candidate_id for item in playlist.items}
    inserted_items = _playlist_items_from_candidates(
        candidates,
        inserted_by=PlaylistItemSource.refill,
        limit=slots,
        existing_candidate_ids=existing_candidate_ids,
    )
    if not inserted_items:
        return PlaylistMutationResult(
            playlist=playlist,
            warnings=["No new playable music was available to extend the playlist."],
        )

    next_items = [*kept_items, *inserted_items]
    next_playlist = playlist.model_copy(
        update={
            "items": next_items,
            "current_index": previous_keep,
            "revision": playlist.revision + 1,
            "updated_at": datetime.now(UTC),
        }
    )
    return PlaylistMutationResult(
        playlist=next_playlist,
        dropped_items=dropped_items,
        inserted_items=inserted_items,
    )


def retune_playlist_after_current(
    playlist: RadioPlaylist,
    candidates: list[CandidateItem],
) -> PlaylistMutationResult:
    if not playlist.items:
        next_playlist = create_playlist_from_candidates(
            candidates,
            inserted_by=PlaylistItemSource.user_request,
            target_size=playlist.target_size,
            refill_threshold=playlist.refill_threshold,
        )
        warnings = [] if next_playlist.items else ["No playable music matched the new request."]
        return PlaylistMutationResult(playlist=next_playlist, warnings=warnings)

    previous_items = playlist.items[: playlist.current_index]
    current_item = playlist.items[playlist.current_index]
    before_and_current = [current_item]
    after = playlist.items[playlist.current_index + 1 :]
    existing_candidate_ids = {item.candidate_id for item in playlist.items}
    replacement_slots = max(0, playlist.target_size - len(before_and_current))
    replacement_items = _playlist_items_from_candidates(
        candidates,
        inserted_by=PlaylistItemSource.user_request,
        limit=replacement_slots,
        existing_candidate_ids=existing_candidate_ids,
    )

    if not replacement_items:
        return PlaylistMutationResult(
            playlist=playlist,
            warnings=["No playable music matched the new request; keeping the current queue."],
        )

    replaced_count = min(len(after), len(replacement_items))
    dropped_items = [*previous_items, *after[:replaced_count]]
    retained_after = after[replaced_count:]
    next_items = [
        *before_and_current,
        *replacement_items,
        *retained_after,
    ][: playlist.target_size]

    if len(replacement_items) < len(after):
        warnings = [
            "Only part of the upcoming playlist was replaced; the remaining songs were kept."
        ]
    else:
        warnings = []

    next_playlist = playlist.model_copy(
        update={
            "items": next_items,
            "current_index": 0,
            "revision": playlist.revision + 1,
            "updated_at": datetime.now(UTC),
        }
    )
    return PlaylistMutationResult(
        playlist=next_playlist,
        dropped_items=dropped_items,
        inserted_items=replacement_items,
        warnings=warnings,
    )


def current_playlist_item(playlist: RadioPlaylist | None) -> PlaylistItem | None:
    if playlist is None or not playlist.items:
        return None
    if playlist.current_index >= len(playlist.items):
        return None
    return playlist.items[playlist.current_index]


def record_playlist_events(
    *,
    user_id: str,
    items: list[PlaylistItem],
    event_type: str,
) -> None:
    for item in items:
        save_history_event(
            user_id=user_id,
            candidate_id=item.candidate_id,
            event_type=event_type,
            title=item.title,
            creator=item.creator,
        )


def _playlist_items_from_candidates(
    candidates: list[CandidateItem],
    *,
    inserted_by: PlaylistItemSource,
    limit: int,
    existing_candidate_ids: set[str],
) -> list[PlaylistItem]:
    if limit <= 0:
        return []

    items: list[PlaylistItem] = []
    seen_candidate_ids = set(existing_candidate_ids)
    for candidate in candidates:
        if candidate.content_type is not ContentType.music:
            continue
        if candidate.candidate_id in seen_candidate_ids:
            continue
        items.append(
            PlaylistItem(
                item_id=f"playlist-item-{uuid4().hex}",
                candidate_id=candidate.candidate_id,
                title=candidate.title,
                creator=candidate.creator,
                duration_seconds=candidate.duration_seconds,
                playback_url=candidate.playback_url,
                source=candidate.source,
                tags=candidate.tags,
                metadata=candidate.metadata,
                inserted_by=inserted_by,
                recommendation_kind=_recommendation_kind(candidate),
            )
        )
        seen_candidate_ids.add(candidate.candidate_id)
        if len(items) >= limit:
            break

    return items


def _recommendation_kind(candidate: CandidateItem) -> PlaylistRecommendationKind:
    source = candidate.source.lower()
    tags = {tag.lower() for tag in candidate.tags}

    if source.startswith("mock") or str(candidate.playback_url or "").startswith("mock://"):
        return PlaylistRecommendationKind.mock_fallback

    recommendation_tags = {
        "user_preference",
        "recent_favorite",
        "liked_track",
        "playlist_seed",
        "personalized_recommendation",
        "daily_recommend",
        "recommended_playlist_seed",
        "favorite_artist_match",
        "favorite_genre_match",
    }
    if source == "netease_cloud_music" and tags.intersection(recommendation_tags):
        return PlaylistRecommendationKind.real_recommendation

    if "fallback_search" in tags or "broad_fallback" in tags:
        return PlaylistRecommendationKind.mock_fallback

    return PlaylistRecommendationKind.real_search
