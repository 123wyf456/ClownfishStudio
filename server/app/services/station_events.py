from __future__ import annotations

from uuid import uuid4

from app.schemas import StationSession, StationSessionEvent

MAX_SESSION_EVENTS = 40


def append_session_event(
    session: StationSession,
    *,
    event_type: str,
    payload: dict[str, str | int | float | bool | None] | None = None,
    event_id: str | None = None,
) -> StationSession:
    event = StationSessionEvent(
        event_id=event_id or f"event-{uuid4().hex}",
        event_type=event_type,
        payload=payload or {},
    )
    next_events = [*session.events, event][-MAX_SESSION_EVENTS:]
    return session.model_copy(update={"events": next_events})
