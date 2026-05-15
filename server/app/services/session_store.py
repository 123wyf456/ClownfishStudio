from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Text, delete, select
from sqlalchemy.engine import Engine

from app.db.session import get_engine
from app.schemas import ChatMessage, ProgramItem, StationSession


@dataclass
class StationSessionState:
    session: StationSession
    chat_history: list[ChatMessage] = field(default_factory=list)
    current_item: ProgramItem | None = None


metadata = MetaData()

station_sessions = Table(
    "station_sessions",
    metadata,
    Column("user_id", String(128), primary_key=True),
    Column("session_json", Text, nullable=False),
    Column("current_item_json", Text, nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

station_chat_messages = Table(
    "station_chat_messages",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", String(128), nullable=False, index=True),
    Column("message_json", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


def save_station_session(state: StationSessionState) -> StationSessionState:
    engine = get_engine()
    _ensure_tables(engine)
    if not state.chat_history:
        existing = get_station_session(state.session.user_id)
        if existing is not None:
            state.chat_history = list(existing.chat_history)

    with engine.begin() as connection:
        connection.execute(
            station_sessions.delete().where(station_sessions.c.user_id == state.session.user_id)
        )
        connection.execute(
            station_sessions.insert().values(
                user_id=state.session.user_id,
                session_json=state.session.model_dump_json(),
                current_item_json=(
                    state.current_item.model_dump_json() if state.current_item is not None else None
                ),
                updated_at=datetime.now(UTC),
            )
        )

        connection.execute(
            station_chat_messages.delete().where(
                station_chat_messages.c.user_id == state.session.user_id
            )
        )
        if state.chat_history:
            connection.execute(
                station_chat_messages.insert(),
                [
                    {
                        "user_id": state.session.user_id,
                        "message_json": message.model_dump_json(),
                        "created_at": message.created_at,
                    }
                    for message in state.chat_history
                ],
            )

    return state


def get_station_session(user_id: str) -> StationSessionState | None:
    engine = get_engine()
    _ensure_tables(engine)

    with engine.begin() as connection:
        session_row = (
            connection.execute(
                select(station_sessions).where(station_sessions.c.user_id == user_id)
            )
            .mappings()
            .first()
        )
        if session_row is None:
            return None

        chat_rows = connection.execute(
            select(station_chat_messages)
            .where(station_chat_messages.c.user_id == user_id)
            .order_by(station_chat_messages.c.id.asc())
        ).mappings()

        session = StationSession.model_validate(json.loads(session_row["session_json"]))
        current_item_json = session_row["current_item_json"]
        current_item = (
            ProgramItem.model_validate(json.loads(current_item_json))
            if isinstance(current_item_json, str) and current_item_json
            else None
        )
        chat_history = [
            ChatMessage.model_validate(json.loads(row["message_json"])) for row in chat_rows
        ]

    return StationSessionState(
        session=session,
        chat_history=chat_history,
        current_item=current_item,
    )


def list_chat_history(user_id: str) -> list[ChatMessage]:
    state = get_station_session(user_id)
    return list(state.chat_history) if state else []


def append_chat_message(user_id: str, message: ChatMessage) -> None:
    engine = get_engine()
    _ensure_tables(engine)

    with engine.begin() as connection:
        has_session = connection.execute(
            select(station_sessions.c.user_id).where(station_sessions.c.user_id == user_id)
        ).first()
        if has_session is None:
            return

        connection.execute(
            station_chat_messages.insert().values(
                user_id=user_id,
                message_json=message.model_dump_json(),
                created_at=message.created_at,
            )
        )


def update_current_item(user_id: str, item: ProgramItem | None) -> None:
    engine = get_engine()
    _ensure_tables(engine)

    with engine.begin() as connection:
        connection.execute(
            station_sessions.update()
            .where(station_sessions.c.user_id == user_id)
            .values(current_item_json=item.model_dump_json() if item is not None else None)
        )


def clear_station_session_store() -> None:
    engine = get_engine()
    _ensure_tables(engine)
    with engine.begin() as connection:
        connection.execute(delete(station_chat_messages))
        connection.execute(delete(station_sessions))


def _ensure_tables(engine: Engine) -> None:
    metadata.create_all(engine)
