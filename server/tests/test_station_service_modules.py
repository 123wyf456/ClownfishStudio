from datetime import UTC, datetime

from app.agents import AgentOutputValidationError
from app.agents.song_request_agent import SongRequestPlan
from app.schemas import (
    CandidateItem,
    ChatMessage,
    ChatRouterResult,
    ContentType,
    DeviceContext,
    GenerateProgramRequest,
    ListeningNeed,
    Mood,
    ProgramBlock,
    ProgramItem,
    ProgramItemType,
    RadioProgram,
    StationChatRequest,
    UserStateInput,
)
from app.services.session_store import StationSessionState
from app.services.station_chat_planner import (
    build_initial_chat_user_state,
    build_router_request_text,
    chat_regeneration_candidate_limit,
    fallback_chat_router_result,
    requires_real_music_candidates,
)
from app.services.station_orchestrator import StationOrchestrator
from app.services.station_reply_presenter import build_reply_metadata, compact_agent_reply
from app.services.station_session_mutations import (
    apply_chat_control,
    apply_refill_generation,
    build_initial_session,
    retune_session_playlist,
)


def test_build_initial_chat_user_state_preserves_raw_user_text() -> None:
    router = ChatRouterResult(need_chat=True, need_music=True, emotion="tired")

    state = build_initial_chat_user_state(message="今天有点累，放慢一点", router=router)

    assert state["free_text"] == "今天有点累，放慢一点"
    assert "companionship" in state["needs"]
    assert "relax" in state["needs"]


def test_build_router_request_text_keeps_original_message_first() -> None:
    router = ChatRouterResult(need_music=True)

    text = build_router_request_text("来点中文歌", router=router)

    assert text.startswith("来点中文歌")


def test_compact_agent_reply_rejects_empty_agent_text() -> None:
    try:
        compact_agent_reply("", fallback_message="陪我听会儿")
    except AgentOutputValidationError as exc:
        assert "LLM chat reply was empty" in str(exc)
    else:
        raise AssertionError("empty LLM reply should not be replaced with a preset answer")


def test_compact_agent_reply_rejects_language_mismatch() -> None:
    try:
        compact_agent_reply(
            "This is a very long English sentence.",
            fallback_message="陪我听会儿",
        )
    except AgentOutputValidationError as exc:
        assert "LLM chat reply language did not match" in str(exc)
    else:
        raise AssertionError("mismatched LLM reply should not be replaced with a preset answer")


def test_fallback_chat_router_result_rejects_non_control_music_request() -> None:
    try:
        fallback_chat_router_result("播放一点安静的歌")
    except AgentOutputValidationError as exc:
        assert "non-control messages require model understanding" in str(exc)
    else:
        raise AssertionError("non-control music requests should be routed by the LLM")


def test_fallback_chat_router_result_keeps_explicit_controls_local() -> None:
    router = fallback_chat_router_result("跳过这首")

    assert router.need_control is True
    assert router.control_action == "skip"
    assert router.need_chat is False
    assert router.need_music is False


def test_requires_real_music_candidates_for_artist_request() -> None:
    router = ChatRouterResult(
        need_music=True,
        music_constraints={"artists": ["周杰伦"], "raw_query": "放点周杰伦"},
    )

    assert requires_real_music_candidates(message="放点周杰伦", router=router) is True
    assert chat_regeneration_candidate_limit(message="放点周杰伦", router=router) == 8


def test_build_initial_session_creates_playlist_and_warning_for_partial_fill() -> None:
    session = build_initial_session(
        user_id="demo-user",
        greeting="你好",
        program=_sample_program(),
        candidate_items=[_candidate("song-1"), _candidate("song-2")],
        generation_warnings=["planner fallback"],
    )

    assert session.greeting == "你好"
    assert session.playlist is not None
    assert len(session.playlist.items) == 2
    assert "planner fallback" in session.warnings
    assert (
        "Only part of the initial playlist could be filled with playable music." in session.warnings
    )
    assert session.events
    assert session.events[0].event_type == "session_created"


def test_retune_session_playlist_keeps_current_item_and_appends_warnings() -> None:
    session = build_initial_session(
        user_id="demo-user",
        greeting="你好",
        program=_sample_program(),
        candidate_items=[_candidate("song-1"), _candidate("song-2"), _candidate("song-3")],
        generation_warnings=[],
    )
    assert session.playlist is not None

    updated = retune_session_playlist(
        session=session,
        message="来点更安静的",
        router=ChatRouterResult(need_music=True),
        program=_sample_program(),
        candidate_items=[_candidate("song-4"), _candidate("song-5")],
        generation_warnings=["retune warning"],
    )

    assert updated.playlist is not None
    assert updated.playlist.items[0].candidate_id == session.playlist.items[0].candidate_id
    assert "retune warning" in updated.warnings


def test_apply_refill_generation_inserts_new_candidates() -> None:
    session = build_initial_session(
        user_id="demo-user",
        greeting="你好",
        program=_sample_program(),
        candidate_items=[
            _candidate("song-1"),
            _candidate("song-2"),
            _candidate("song-3"),
            _candidate("song-4"),
        ],
        generation_warnings=[],
    )
    assert session.playlist is not None
    trimmed_playlist = session.playlist.model_copy(update={"items": session.playlist.items[:2]})
    state = StationSessionState(
        session=session.model_copy(update={"playlist": trimmed_playlist}),
        current_item=trimmed_playlist.items[0],
    )

    updated_state, warnings = apply_refill_generation(
        state=state,
        program=_sample_program(),
        candidate_items=[_candidate("song-5"), _candidate("song-6"), _candidate("song-7")],
        generation_warnings=["refill warning"],
    )

    assert updated_state.session.playlist is not None
    assert len(updated_state.session.playlist.items) >= len(trimmed_playlist.items)
    assert "refill warning" in warnings


def test_apply_chat_control_advances_playlist_for_skip() -> None:
    session = build_initial_session(
        user_id="demo-user",
        greeting="你好",
        program=_sample_program(),
        candidate_items=[_candidate("song-1"), _candidate("song-2"), _candidate("song-3")],
        generation_warnings=[],
    )
    assert session.playlist is not None
    state = StationSessionState(session=session, current_item=session.playlist.items[0])

    updated_state, reply = apply_chat_control(
        state=state,
        chat_history=[],
        router=ChatRouterResult(need_control=True, control_action="skip"),
        message="跳过这首",
    )

    assert updated_state.session.playlist is not None
    assert updated_state.session.playlist.current_index == 1
    assert reply == "好，跳过这首。"
    assert {event.event_type for event in updated_state.session.events} >= {
        "playback_control",
        "feedback_recorded",
    }


def test_apply_chat_control_like_keeps_current_track_and_records_event() -> None:
    session = build_initial_session(
        user_id="demo-user",
        greeting="你好",
        program=_sample_program(),
        candidate_items=[_candidate("song-1"), _candidate("song-2"), _candidate("song-3")],
        generation_warnings=[],
    )
    assert session.playlist is not None
    state = StationSessionState(session=session, current_item=session.playlist.items[0])

    updated_state, reply = apply_chat_control(
        state=state,
        chat_history=[],
        router=ChatRouterResult(need_control=True, control_action="like"),
        message="喜欢这首",
    )

    assert updated_state.session.playlist is not None
    assert updated_state.session.playlist.current_index == 0
    assert reply == "好，我记下你喜欢这首。"
    assert {event.event_type for event in updated_state.session.events} >= {
        "playback_control",
        "feedback_recorded",
    }


def test_build_reply_metadata_tracks_reply_kind_and_playlist_change() -> None:
    metadata = build_reply_metadata(
        reply_kind="music",
        reply_source="agent",
        playlist_changed=True,
        event_id="event-123",
    )

    assert metadata.reply_kind == "music"
    assert metadata.reply_source == "agent"
    assert metadata.playlist_changed is True
    assert metadata.event_id == "event-123"


def test_chat_only_turn_uses_agent_reply_without_retuning_playlist(monkeypatch) -> None:
    runtime = _ChatOnlyRuntime()
    orchestrator = StationOrchestrator(runtime=runtime, song_request_planner=_TestSongPlanner())
    initial = orchestrator.generate_station(
        GenerateProgramRequest(
            user_id="chat-only-user",
            device_context=_device_context(),
            user_state=UserStateInput(
                needs=[ListeningNeed.companionship],
                duration_minutes=25,
                free_text="先开一个电台",
            ),
            max_candidates=8,
        )
    )
    assert initial.session.playlist is not None
    initial_playlist_id = initial.session.playlist.playlist_id
    initial_candidate_ids = [
        item.candidate_id for item in initial.session.playlist.items
    ]

    def fail_generate(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("chat-only turn should not regenerate music candidates")

    monkeypatch.setattr(orchestrator._generation_service, "generate", fail_generate)

    response = orchestrator.chat(
        StationChatRequest(
            user_id="chat-only-user",
            message="给我讲一个笑话",
            device_context=_device_context(),
        )
    )

    assert response.reply.text == "好，为什么电台主持人不怕冷？"
    assert response.reply.metadata is not None
    assert response.reply.metadata.reply_kind == "chat"
    assert response.reply.metadata.playlist_changed is False
    assert response.session.playlist is not None
    assert response.session.playlist.playlist_id == initial_playlist_id
    assert [item.candidate_id for item in response.session.playlist.items] == initial_candidate_ids
    assert runtime.chat_reply_calls == 1


def test_chat_reply_failure_is_not_replaced_with_preset_text(monkeypatch) -> None:
    runtime = _FailingChatRuntime()
    orchestrator = StationOrchestrator(runtime=runtime, song_request_planner=_TestSongPlanner())
    orchestrator.generate_station(
        GenerateProgramRequest(
            user_id="chat-failure-user",
            device_context=_device_context(),
            user_state=UserStateInput(
                needs=[ListeningNeed.companionship],
                duration_minutes=25,
                free_text="先开一个电台",
            ),
            max_candidates=8,
        )
    )

    def fail_generate(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("chat-only failure should not regenerate music candidates")

    monkeypatch.setattr(orchestrator._generation_service, "generate", fail_generate)

    try:
        orchestrator.chat(
            StationChatRequest(
                user_id="chat-failure-user",
                message="陪我聊聊",
                device_context=_device_context(),
            )
        )
    except AgentOutputValidationError as exc:
        assert "LLM chat reply failed" in str(exc)
    else:
        raise AssertionError("failed LLM chat reply should not use a preset fallback")


def _candidate(candidate_id: str) -> CandidateItem:
    index = int(candidate_id.split("-")[-1])
    return CandidateItem(
        candidate_id=candidate_id,
        content_type=ContentType.music,
        title=f"Song {index}",
        creator=f"Artist {index}",
        duration_seconds=180,
        playback_url=f"https://example.com/{candidate_id}.mp3",
        tags=["search_result"],
        source="netease_cloud_music",
    )


def _device_context() -> DeviceContext:
    return DeviceContext(
        local_time=datetime(2026, 4, 30, 22, 30, tzinfo=UTC),
        timezone="Asia/Shanghai",
        locale="zh-CN",
        city_hint="Shanghai",
    )


class _ChatOnlyRuntime:
    chat_reply_calls = 0

    def generate_program(self, **kwargs):  # noqa: ANN003
        del kwargs
        return _sample_program()

    def generate_chat_reply(
        self,
        *,
        session,
        message: str,
        chat_history: list[ChatMessage] | None = None,
    ) -> str:
        del session, message, chat_history
        self.chat_reply_calls += 1
        return "好，为什么电台主持人不怕冷？因为他一直有热歌。"

    def plan_chat_turn(
        self,
        *,
        session,
        message: str,
        chat_history: list[ChatMessage] | None = None,
    ) -> ChatRouterResult:
        del session, message, chat_history
        return ChatRouterResult(need_chat=True, need_music=False, confidence=0.95)


class _TestSongPlanner:
    def plan(self, *, message: str, memory, weather, **kwargs) -> SongRequestPlan:  # noqa: ANN001
        del memory, weather, kwargs
        return SongRequestPlan(
            intent=message or "test station",
            search_queries=["late night"],
            preferred_title=None,
            preferred_artist=None,
            preferred_tags=["quiet"],
            mode="mood_mix",
            reason="test double",
        )


class _FailingChatRuntime(_ChatOnlyRuntime):
    def generate_chat_reply(
        self,
        *,
        session,
        message: str,
        chat_history: list[ChatMessage] | None = None,
    ) -> str:
        del session, message, chat_history
        raise RuntimeError("LLM unavailable")


def _sample_program() -> RadioProgram:
    return RadioProgram(
        program_id="program-1",
        title="Night Radio",
        summary="Quiet night set.",
        context_snapshot={
            "device_context": DeviceContext(
                local_time=datetime(2026, 4, 30, 22, 30, tzinfo=UTC),
                timezone="Asia/Shanghai",
                locale="zh-CN",
                city_hint="Shanghai",
            ),
            "user_state": UserStateInput(
                mood=Mood.tired,
                needs=[ListeningNeed.relax, ListeningNeed.companionship],
                duration_minutes=25,
                free_text="今晚想安静一点。",
            ),
            "weather": {"condition": "Cloudy", "temperature_celsius": 26},
            "calendar_events": [],
        },
        blocks=[
            ProgramBlock(
                block_id="block-1",
                title="Opening",
                position=0,
                items=[
                    ProgramItem(
                        item_id="narration-1",
                        item_type=ProgramItemType.narration,
                        title="Opening",
                        position=0,
                        narration_text="晚上好。",
                    ),
                    ProgramItem(
                        item_id="music-1",
                        item_type=ProgramItemType.music,
                        title="Song 1",
                        creator="Artist 1",
                        position=1,
                        candidate_id="song-1",
                    ),
                ],
            )
        ],
        total_duration_minutes=25,
    )
