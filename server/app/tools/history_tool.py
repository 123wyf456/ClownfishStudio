from datetime import UTC, datetime
from uuid import uuid4

from app.schemas import RadioProgram
from app.tools.mock_data import read_mock_json

HistoryEvent = dict[str, str]
_SAVED_HISTORY_EVENTS: list[HistoryEvent] | None = None


def get_recent_history(user_id: str, limit: int = 20) -> list[HistoryEvent]:
    user_events = [
        event
        for event in _get_history_store()
        if isinstance(event, dict) and event.get("user_id") == user_id
    ]
    sorted_events = sorted(
        user_events,
        key=lambda event: str(event.get("occurred_at", "")),
        reverse=True,
    )
    return [dict(event) for event in sorted_events[:limit]]


def get_recent_candidate_ids(user_id: str, limit: int = 20) -> list[str]:
    candidate_ids: list[str] = []

    for event in get_recent_history(user_id=user_id, limit=limit):
        candidate_id = event.get("candidate_id")
        if candidate_id:
            candidate_ids.append(candidate_id)

    return candidate_ids


def save_history_event(
    user_id: str,
    candidate_id: str,
    event_type: str,
    occurred_at: str | None = None,
    title: str | None = None,
    creator: str | None = None,
) -> HistoryEvent:
    event: HistoryEvent = {
        "event_id": f"history-{uuid4().hex}",
        "user_id": user_id,
        "candidate_id": candidate_id,
        "event_type": event_type,
        "occurred_at": occurred_at or datetime.now(UTC).isoformat(),
    }
    if title:
        event["title"] = title
    if creator:
        event["creator"] = creator

    _get_history_store().append(event)
    return dict(event)


def save_program_history(
    user_id: str,
    program: RadioProgram,
    event_type: str = "recommended",
) -> list[HistoryEvent]:
    saved_events: list[HistoryEvent] = []
    seen_candidate_ids: set[str] = set()

    for block in program.blocks:
        for item in block.items:
            if item.candidate_id is None or item.candidate_id in seen_candidate_ids:
                continue

            seen_candidate_ids.add(item.candidate_id)
            saved_events.append(
                save_history_event(
                    user_id=user_id,
                    candidate_id=item.candidate_id,
                    event_type=event_type,
                    occurred_at=program.generated_at.isoformat(),
                    title=item.title,
                    creator=item.creator,
                )
            )

    return saved_events


def _get_history_store() -> list[HistoryEvent]:
    global _SAVED_HISTORY_EVENTS

    if _SAVED_HISTORY_EVENTS is None:
        data = read_mock_json("history.json")
        events = data["events"]
        if not isinstance(events, list):
            raise ValueError("history mock data is malformed")

        _SAVED_HISTORY_EVENTS = [
            dict(event)
            for event in events
            if isinstance(event, dict)
            and all(isinstance(key, str) and isinstance(value, str) for key, value in event.items())
        ]

    return _SAVED_HISTORY_EVENTS
