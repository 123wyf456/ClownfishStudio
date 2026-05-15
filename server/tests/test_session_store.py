from datetime import UTC, datetime

from app.schemas import (
    ChatMessage,
    ContextSnapshot,
    DeviceContext,
    ProgramBlock,
    ProgramItem,
    ProgramItemType,
    RadioProgram,
    StationSession,
    UserStateInput,
)
from app.services.session_store import (
    StationSessionState,
    append_chat_message,
    get_station_session,
    save_station_session,
    update_current_item,
)


def test_station_session_store_persists_session_chat_and_current_item() -> None:
    session = make_session()
    current_item = session.program.blocks[0].items[1]
    save_station_session(StationSessionState(session=session, current_item=current_item))

    append_chat_message("sqlite-user", ChatMessage(role="user", text="想听安静一点"))
    append_chat_message("sqlite-user", ChatMessage(role="assistant", text="我把频道放慢一点。"))
    update_current_item("sqlite-user", current_item)

    restored = get_station_session("sqlite-user")

    assert restored is not None
    assert restored.session.session_id == "session-sqlite"
    assert restored.current_item is not None
    assert restored.current_item.candidate_id == "music-sqlite"
    assert [message.role for message in restored.chat_history] == ["user", "assistant"]
    assert restored.chat_history[0].text == "想听安静一点"


def make_session() -> StationSession:
    device_context = DeviceContext(
        local_time=datetime(2026, 5, 14, 22, 30, tzinfo=UTC),
        timezone="Asia/Shanghai",
        city_hint="Shanghai",
    )
    user_state = UserStateInput(duration_minutes=25, free_text="今晚放松一点")
    context_snapshot = ContextSnapshot(
        device_context=device_context,
        user_state=user_state,
        weather={"city": "Shanghai", "condition": "rain"},
    )
    program = RadioProgram(
        program_id="program-sqlite",
        title="SQLite Radio",
        summary="A persisted station.",
        context_snapshot=context_snapshot,
        blocks=[
            ProgramBlock(
                block_id="block-0",
                title="Opening",
                position=0,
                items=[
                    ProgramItem(
                        item_id="item-0",
                        item_type=ProgramItemType.narration,
                        title="Opening",
                        position=0,
                        narration_text="今晚慢一点。",
                    ),
                    ProgramItem(
                        item_id="item-1",
                        item_type=ProgramItemType.music,
                        title="Quiet Song",
                        creator="Quiet Artist",
                        position=1,
                        candidate_id="music-sqlite",
                        playback_url="mock://music-sqlite",
                        duration_seconds=180,
                    ),
                ],
            )
        ],
        total_duration_minutes=25,
    )
    return StationSession(
        session_id="session-sqlite",
        user_id="sqlite-user",
        greeting="今晚慢一点。",
        program=program,
        weather={"city": "Shanghai", "condition": "rain"},
    )
