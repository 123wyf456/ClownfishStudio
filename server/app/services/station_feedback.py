from __future__ import annotations

from app.schemas import FeedbackEvent, FeedbackType, PlaylistItem, ProgramItem, StationSession
from app.services.playlist_runtime import current_playlist_item
from app.services.station_events import append_session_event
from app.tools import build_memory_update_hint, save_feedback, save_memory_update_hint


def record_feedback_for_control(
    *,
    session: StationSession,
    action: str | None,
    current_item: PlaylistItem | ProgramItem | None = None,
) -> StationSession:
    feedback_type = _feedback_type_for_action(action)
    if feedback_type is None or session.program is None:
        return session

    feedback_item = current_item or current_playlist_item(session.playlist)
    feedback = FeedbackEvent(
        feedback_type=feedback_type,
        user_id=session.user_id,
        program_id=session.program.program_id,
        item_id=feedback_item.item_id if feedback_item is not None else None,
        candidate_id=feedback_item.candidate_id if feedback_item is not None else None,
    )
    saved_feedback = save_feedback(feedback)
    save_memory_update_hint(build_memory_update_hint(saved_feedback))
    return append_session_event(
        session,
        event_type="feedback_recorded",
        payload={
            "action": action or "",
            "feedback_type": feedback_type.value,
            "candidate_id": saved_feedback.candidate_id,
        },
    )


def _feedback_type_for_action(action: str | None) -> FeedbackType | None:
    if action == "like" or action == "favorite":
        return FeedbackType.like
    if action == "skip":
        return FeedbackType.skip
    return None
