from __future__ import annotations

from uuid import uuid4

from app.schemas import (
    CandidateItem,
    ChatMessage,
    ChatRouterResult,
    PlayerAdvanceReason,
    PlaylistItemSource,
    RadioProgram,
    StationSession,
)
from app.services.playlist_runtime import (
    advance_playlist,
    create_playlist_from_candidates,
    current_playlist_item,
    record_playlist_events,
    refill_playlist,
    retune_playlist_after_current,
)
from app.services.session_store import (
    StationSessionState,
    save_station_session,
    update_current_item,
)
from app.services.station_events import append_session_event
from app.services.station_feedback import record_feedback_for_control
from app.services.station_reply_presenter import (
    compact_agent_reply,
    control_reply,
    fallback_chat_reply,
)


def build_initial_session(
    *,
    user_id: str,
    greeting: str,
    program: RadioProgram,
    candidate_items: list[CandidateItem],
    generation_warnings: list[str],
) -> StationSession:
    weather = program.context_snapshot.weather
    calendar_events = program.context_snapshot.calendar_events
    selected_candidates = program_music_candidates(program=program, candidate_items=candidate_items)
    if not selected_candidates:
        selected_candidates = music_candidates(candidate_items)
    playlist = create_playlist_from_candidates(
        selected_candidates,
        inserted_by=PlaylistItemSource.initial,
    )

    warnings = [*generation_warnings]
    if len(playlist.items) < playlist.target_size:
        warnings.append("Only part of the initial playlist could be filled with playable music.")

    session = StationSession(
        session_id=f"session-{uuid4().hex}",
        user_id=user_id,
        greeting=greeting,
        tts_text=None,
        tts_audio_url=None,
        program=program.model_copy(
            update={
                "context_snapshot": program.context_snapshot.model_copy(
                    update={"calendar_events": calendar_events, "weather": weather}
                )
            }
        ),
        playlist=playlist,
        weather=weather,
        calendar_events=calendar_events,
        warnings=warnings,
    )
    return append_session_event(
        session,
        event_type="session_created",
        payload={
            "playlist_size": len(playlist.items),
            "warning_count": len(warnings),
        },
    )


def retune_session_playlist(
    *,
    session: StationSession,
    message: str,
    router: ChatRouterResult,
    program: RadioProgram,
    candidate_items: list[CandidateItem],
    generation_warnings: list[str],
) -> StationSession:
    playlist = session.playlist
    if playlist is None:
        playlist = create_playlist_from_candidates(
            program_music_candidates(
                program=program,
                candidate_items=candidate_items,
            ),
            inserted_by=PlaylistItemSource.user_request,
        )
        mutation_warnings: list[str] = []
    else:
        mutation = retune_playlist_after_current(
            playlist,
            program_music_candidates(
                program=program,
                candidate_items=candidate_items,
            ),
        )
        playlist = mutation.playlist
        mutation_warnings = mutation.warnings
        if mutation.dropped_items:
            record_playlist_events(
                user_id=session.user_id,
                items=mutation.dropped_items,
                event_type="dropped",
            )
        if mutation.inserted_items:
            record_playlist_events(
                user_id=session.user_id,
                items=mutation.inserted_items,
                event_type="inserted",
            )

    updated_session = session.model_copy(
        update={
            "greeting": compact_agent_reply(
                fallback_chat_reply(message=message, router=router),
                fallback_message=message,
            ),
            "playlist": playlist,
            "warnings": [
                *session.warnings,
                *generation_warnings,
                *mutation_warnings,
            ],
        }
    )
    return append_session_event(
        updated_session,
        event_type="playlist_retuned",
        payload={
            "inserted_count": len(candidate_items),
            "warning_count": len(generation_warnings) + len(mutation_warnings),
        },
    )


def apply_refill_generation(
    *,
    state: StationSessionState,
    program: RadioProgram,
    candidate_items: list[CandidateItem],
    generation_warnings: list[str],
) -> tuple[StationSessionState, list[str]]:
    playlist = state.session.playlist
    if playlist is None:
        return state, generation_warnings

    mutation = refill_playlist(
        playlist,
        program_music_candidates(
            program=program,
            candidate_items=candidate_items,
        ),
    )
    if mutation.dropped_items:
        record_playlist_events(
            user_id=state.session.user_id,
            items=mutation.dropped_items,
            event_type="dropped",
        )
    if mutation.inserted_items:
        record_playlist_events(
            user_id=state.session.user_id,
            items=mutation.inserted_items,
            event_type="inserted",
        )

    warnings = [*generation_warnings, *mutation.warnings]
    updated_state = StationSessionState(
        session=state.session.model_copy(
            update={
                "playlist": mutation.playlist,
                "warnings": [*state.session.warnings, *warnings],
            }
        ),
        chat_history=state.chat_history,
        current_item=current_playlist_item(mutation.playlist),
    )
    save_station_session(updated_state)
    return updated_state, warnings


def apply_chat_control(
    *,
    state: StationSessionState,
    chat_history: list[ChatMessage],
    router: ChatRouterResult,
    message: str,
) -> tuple[StationSessionState, str]:
    playlist = state.session.playlist
    action = router.control_action
    if playlist is None or action not in {"next", "previous", "skip", "like", "favorite"}:
        if action in {"like", "favorite"}:
            updated_session = record_feedback_for_control(session=state.session, action=action)
            updated_session = append_session_event(
                updated_session,
                event_type="playback_control",
                payload={"action": action},
            )
            updated_state = StationSessionState(
                session=updated_session,
                chat_history=chat_history,
                current_item=state.current_item,
            )
            save_station_session(updated_state)
            return updated_state, control_reply(
                action=action,
                message=message,
                has_session=playlist is not None,
            )
        return state, control_reply(
            action=action,
            message=message,
            has_session=playlist is not None,
        )

    if action in {"like", "favorite"}:
        updated_session = record_feedback_for_control(session=state.session, action=action)
        updated_session = append_session_event(
            updated_session,
            event_type="playback_control",
            payload={"action": action},
        )
        updated_state = StationSessionState(
            session=updated_session,
            chat_history=chat_history,
            current_item=current_playlist_item(updated_session.playlist),
        )
        save_station_session(updated_state)
        return updated_state, control_reply(
            action=action,
            message=message,
            has_session=True,
        )

    reason = (
        PlayerAdvanceReason.previous
        if action == "previous"
        else PlayerAdvanceReason.skip
        if action == "skip"
        else PlayerAdvanceReason.next
    )
    current_before = current_playlist_item(playlist)
    advanced_playlist = advance_playlist(playlist, reason=reason)
    if current_before is not None and advanced_playlist.current_index != playlist.current_index:
        record_playlist_events(
            user_id=state.session.user_id,
            items=[current_before],
            event_type=reason.value,
        )

    updated_session = state.session.model_copy(update={"playlist": advanced_playlist})
    updated_session = append_session_event(
        updated_session,
        event_type="playback_control",
        payload={
            "action": action or "",
            "reason": reason.value,
            "current_index": advanced_playlist.current_index,
        },
    )
    updated_session = record_feedback_for_control(
        session=updated_session,
        action=action,
        current_item=current_before,
    )

    updated_state = StationSessionState(
        session=updated_session,
        chat_history=chat_history,
        current_item=current_playlist_item(advanced_playlist),
    )
    save_station_session(updated_state)
    if updated_state.current_item is not None:
        update_current_item(state.session.user_id, updated_state.current_item)

    return updated_state, control_reply(
        action=action,
        message=message,
        has_session=True,
    )


def program_music_candidates(
    *,
    program: RadioProgram,
    candidate_items: list[CandidateItem],
) -> list[CandidateItem]:
    candidates_by_id = {candidate.candidate_id: candidate for candidate in candidate_items}
    selected_candidates: list[CandidateItem] = []
    seen_candidate_ids: set[str] = set()

    for block in program.blocks:
        for item in block.items:
            if item.item_type != "music" or item.candidate_id is None:
                continue
            if item.candidate_id in seen_candidate_ids:
                continue
            candidate = candidates_by_id.get(item.candidate_id)
            if candidate is None:
                continue
            selected_candidates.append(candidate)
            seen_candidate_ids.add(item.candidate_id)

    if len(selected_candidates) >= min(8, len(music_candidates(candidate_items))):
        return selected_candidates

    selected_candidates.extend(
        candidate
        for candidate in music_candidates(candidate_items)
        if candidate.candidate_id not in seen_candidate_ids
    )
    return selected_candidates


def music_candidates(candidate_items: list[CandidateItem]) -> list[CandidateItem]:
    return [candidate for candidate in candidate_items if candidate.content_type == "music"]
