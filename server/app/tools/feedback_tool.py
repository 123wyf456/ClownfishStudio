from app.schemas import FeedbackEvent, FeedbackType
from app.tools.mock_data import read_mock_json

_SAVED_FEEDBACK_EVENTS: list[FeedbackEvent] | None = None
_SAVED_MEMORY_UPDATE_HINTS: list[dict[str, str]] | None = None


def save_feedback(feedback: FeedbackEvent) -> FeedbackEvent:
    _get_feedback_store().append(feedback)
    return feedback


def list_feedback_events(
    user_id: str | None = None,
    program_id: str | None = None,
) -> list[FeedbackEvent]:
    events = _get_feedback_store()

    if user_id is not None:
        events = [event for event in events if event.user_id == user_id]

    if program_id is not None:
        events = [event for event in events if event.program_id == program_id]

    return list(events)


def build_memory_update_hint(feedback: FeedbackEvent) -> dict[str, str]:
    match feedback.feedback_type:
        case FeedbackType.like | FeedbackType.want_more_like_this:
            action = "increase_affinity"
        case FeedbackType.dislike | FeedbackType.less_like_this:
            action = "decrease_affinity"
        case FeedbackType.too_familiar:
            action = "reduce_repetition"
        case FeedbackType.skip:
            action = "record_skip"

    return {
        "action": action,
        "user_id": feedback.user_id,
        "program_id": feedback.program_id,
        "candidate_id": feedback.candidate_id or "",
    }


def save_memory_update_hint(hint: dict[str, str]) -> dict[str, str]:
    _get_memory_update_hint_store().append(hint)
    return hint


def list_memory_update_hints(
    user_id: str | None = None,
    actions: set[str] | None = None,
) -> list[dict[str, str]]:
    hints = _get_memory_update_hint_store()

    if user_id is not None:
        hints = [hint for hint in hints if hint.get("user_id") == user_id]

    if actions is not None:
        hints = [hint for hint in hints if hint.get("action") in actions]

    return [dict(hint) for hint in hints]


def _get_feedback_store() -> list[FeedbackEvent]:
    global _SAVED_FEEDBACK_EVENTS

    if _SAVED_FEEDBACK_EVENTS is None:
        data = read_mock_json("feedback_events.json")
        events = data["events"]
        if not isinstance(events, list):
            raise ValueError("feedback mock data is malformed")

        _SAVED_FEEDBACK_EVENTS = [
            FeedbackEvent.model_validate(event) for event in events if isinstance(event, dict)
        ]

    return _SAVED_FEEDBACK_EVENTS


def _get_memory_update_hint_store() -> list[dict[str, str]]:
    global _SAVED_MEMORY_UPDATE_HINTS

    if _SAVED_MEMORY_UPDATE_HINTS is None:
        data = read_mock_json("memory_update_hints.json")
        hints = data["hints"]
        if not isinstance(hints, list):
            raise ValueError("memory update hint mock data is malformed")

        _SAVED_MEMORY_UPDATE_HINTS = [
            dict(hint)
            for hint in hints
            if isinstance(hint, dict)
            and all(isinstance(key, str) and isinstance(value, str) for key, value in hint.items())
        ]

    return _SAVED_MEMORY_UPDATE_HINTS
