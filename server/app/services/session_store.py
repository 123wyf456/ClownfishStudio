from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas import ChatMessage, ProgramItem, StationSession


@dataclass
class StationSessionState:
    session: StationSession
    chat_history: list[ChatMessage] = field(default_factory=list)
    current_item: ProgramItem | None = None


_SESSION_STORE: dict[str, StationSessionState] = {}


def save_station_session(state: StationSessionState) -> StationSessionState:
    existing = _SESSION_STORE.get(state.session.user_id)
    if existing is not None and not state.chat_history:
        state.chat_history = list(existing.chat_history)

    _SESSION_STORE[state.session.user_id] = state
    return state


def get_station_session(user_id: str) -> StationSessionState | None:
    return _SESSION_STORE.get(user_id)


def list_chat_history(user_id: str) -> list[ChatMessage]:
    state = get_station_session(user_id)
    return list(state.chat_history) if state else []


def append_chat_message(user_id: str, message: ChatMessage) -> None:
    state = get_station_session(user_id)
    if state is None:
        return
    state.chat_history.append(message)


def update_current_item(user_id: str, item: ProgramItem | None) -> None:
    state = get_station_session(user_id)
    if state is None:
        return
    state.current_item = item
