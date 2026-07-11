from __future__ import annotations

import logging
from threading import Lock
from time import monotonic

from app.agents import AgentOutputValidationError, RadioAgentRuntime
from app.agents.song_request_agent import SongRequestPlanner
from app.schemas import (
    ChatMessage,
    ChatRouterResult,
    GenerateProgramRequest,
    GenerateProgramResponse,
    PlayerAdvanceRequest,
    PlayerAdvanceResponse,
    PlayerNowResponse,
    ProgramItem,
    RuntimeStatus,
    StationChatRequest,
    StationChatResponse,
    StationGenerateResponse,
    StationSession,
)
from app.services.playlist_runtime import (
    advance_playlist,
    current_playlist_item,
    playlist_needs_refill,
    record_playlist_events,
)
from app.services.program_generation import ProgramGenerationService
from app.services.providers import build_runtime_status
from app.services.session_store import (
    StationSessionState,
    append_chat_message,
    get_station_session,
    list_chat_history,
    save_station_session,
    update_current_item,
)
from app.services.station_chat_planner import (
    build_initial_chat_user_state,
    build_router_request_text,
    chat_regeneration_candidate_limit,
    fallback_chat_router_result,
    requires_real_music_candidates,
    router_has_content,
    router_log_label,
)
from app.services.station_events import append_session_event
from app.services.station_reply_presenter import (
    build_reply_metadata,
    compact_agent_reply,
    control_reply,
)
from app.services.station_session_mutations import (
    apply_chat_control,
    build_initial_session,
    retune_session_playlist,
)
from app.services.station_session_mutations import (
    apply_refill_generation as apply_refill_generation_to_state,
)
from app.services.station_tts import synthesize_session_text

LOGGER = logging.getLogger(__name__)
_LOCKS_LOCK = Lock()
_USER_GENERATION_LOCKS: dict[str, Lock] = {}


class NoSuitableSongError(RuntimeError):
    pass


class StationOrchestrator:
    def __init__(
        self,
        runtime: RadioAgentRuntime | None = None,
        song_request_planner: SongRequestPlanner | None = None,
    ) -> None:
        self._runtime = runtime or RadioAgentRuntime()
        self._generation_service = ProgramGenerationService(
            runtime=self._runtime,
            song_request_planner=song_request_planner,
        )

    def generate_station(self, request: GenerateProgramRequest) -> StationGenerateResponse:
        with _generation_lock_for_user(request.user_id):
            return self._generate_station_unlocked(request=request)

    def _generate_station_unlocked(
        self,
        request: GenerateProgramRequest,
        chat_history: list[ChatMessage] | None = None,
    ) -> StationGenerateResponse:
        timings: dict[str, float] = {}
        started_at = monotonic()
        generation = self._generation_service.generate(
            request=request,
            chat_history=chat_history,
        )
        timings["program_generation"] = monotonic() - started_at

        step_started_at = monotonic()
        greeting = compact_agent_reply(
            _opening_narration(generation.program) or generation.program.summary,
            fallback_message=request.user_state.free_text or "",
        )
        timings["derive_greeting"] = monotonic() - step_started_at

        session = build_initial_session(
            user_id=request.user_id,
            greeting=greeting,
            program=generation.program,
            candidate_items=generation.candidate_items,
            generation_warnings=generation.warnings,
        )
        session = synthesize_session_text(session=session, text=greeting)
        session = append_session_event(
            session,
            event_type="reply_generated",
            payload={
                "reply_kind": "greeting",
                "reply_source": "agent",
                "playlist_changed": bool(session.playlist and session.playlist.items),
            },
            event_id=f"reply-{request.user_id}-greeting",
        )
        current_item = current_playlist_item(session.playlist)

        step_started_at = monotonic()
        save_station_session(
            StationSessionState(
                session=session,
                current_item=current_item,
            )
        )
        timings["session_persistence"] = monotonic() - step_started_at

        step_started_at = monotonic()
        runtime = self.runtime_status()
        timings["runtime_status"] = monotonic() - step_started_at
        timings["total"] = monotonic() - started_at
        LOGGER.info(
            "station_generation_timing user_id=%s timings=%s",
            request.user_id,
            {key: round(value, 3) for key, value in timings.items()},
        )

        return StationGenerateResponse(
            session=session,
            candidate_count=generation.candidate_count,
            runtime=runtime,
        )

    def chat(self, request: StationChatRequest) -> StationChatResponse:
        with _generation_lock_for_user(request.user_id):
            return self._chat_unlocked(request)

    def _chat_unlocked(self, request: StationChatRequest) -> StationChatResponse:
        started_at = monotonic()
        timings: dict[str, float] = {}

        step_started_at = monotonic()
        state = get_station_session(request.user_id)
        timings["load_session"] = monotonic() - step_started_at

        user_message = ChatMessage(role="user", text=request.message)
        if state is None:
            step_started_at = monotonic()
            pending_session = StationSession(
                session_id="pending",
                user_id=request.user_id,
                greeting="pending",
            )
            router = self._plan_chat_turn_with_fallback(
                session=pending_session,
                message=request.message,
                chat_history=[user_message],
            )
            route_label = router_log_label(router)
            timings["agent_router"] = monotonic() - step_started_at

            session_response = self._generate_station_unlocked(
                GenerateProgramRequest(
                    user_id=request.user_id,
                    device_context=request.device_context,
                    user_state=build_initial_chat_user_state(
                        message=request.message,
                        router=router,
                    ),
                    max_candidates=8,
                ),
                chat_history=[user_message],
            )

            step_started_at = monotonic()
            append_chat_message(request.user_id, user_message)
            chat_history = list_chat_history(request.user_id)
            timings["append_user_message"] = monotonic() - step_started_at

            step_started_at = monotonic()
            if router.need_control and not router_has_content(router):
                reply_text = compact_agent_reply(
                    control_reply(
                        action=router.control_action,
                        message=request.message,
                        has_session=False,
                    ),
                    fallback_message=request.message,
                )
            else:
                reply_text = self._generate_dj_reply(
                    session=session_response.session,
                    message=request.message,
                    chat_history=chat_history,
                )
            timings["agent_chat_reply"] = monotonic() - step_started_at

            reply = ChatMessage(role="assistant", text=reply_text)
            reply.metadata = build_reply_metadata(
                reply_kind=_reply_kind_from_router(router),
                reply_source=(
                    "control" if router.need_control and not router_has_content(router) else "agent"
                ),
                playlist_changed=bool(session_response.session.playlist),
                event_id=f"reply-{request.user_id}-created",
            )
            refreshed_session = synthesize_session_text(
                session=session_response.session,
                text=reply_text,
            )
            refreshed_session = append_session_event(
                refreshed_session,
                event_type="reply_generated",
                payload={
                    "reply_kind": reply.metadata.reply_kind,
                    "reply_source": reply.metadata.reply_source,
                    "playlist_changed": reply.metadata.playlist_changed,
                },
                event_id=reply.metadata.event_id,
            )
            save_station_session(
                StationSessionState(
                    session=refreshed_session,
                    chat_history=chat_history,
                    current_item=current_playlist_item(refreshed_session.playlist),
                )
            )
            step_started_at = monotonic()
            append_chat_message(request.user_id, reply)
            timings["append_agent_reply"] = monotonic() - step_started_at

            step_started_at = monotonic()
            current_state = get_station_session(request.user_id)
            timings["reload_session"] = monotonic() - step_started_at
            if current_state is None:
                raise RuntimeError("station session was not created")

            timings["total"] = monotonic() - started_at
            LOGGER.info(
                "station_chat_timing user_id=%s route=%s created_session=true timings=%s",
                request.user_id,
                route_label,
                {key: round(value, 3) for key, value in timings.items()},
            )
            return StationChatResponse(
                reply=reply,
                session=current_state.session,
                runtime=self.runtime_status(),
            )

        seed_session = state.session

        step_started_at = monotonic()
        append_chat_message(request.user_id, user_message)
        timings["append_user_message"] = monotonic() - step_started_at

        step_started_at = monotonic()
        chat_history = list_chat_history(request.user_id)
        timings["load_chat_history"] = monotonic() - step_started_at

        step_started_at = monotonic()
        router = self._plan_chat_turn_with_fallback(
            session=seed_session,
            message=request.message,
            chat_history=chat_history,
        )
        route_label = router_log_label(router)
        timings["agent_router"] = monotonic() - step_started_at

        working_state = state
        seed_session = working_state.session
        control_reply_text: str | None = None
        if router.need_control:
            working_state, control_reply_text = self._apply_chat_control(
                state=working_state,
                chat_history=chat_history,
                router=router,
                message=request.message,
            )
            seed_session = working_state.session

        if router.need_control and not router_has_content(router):
            reply_text = compact_agent_reply(
                control_reply_text
                or control_reply(
                    action=router.control_action,
                    message=request.message,
                    has_session=True,
                ),
                fallback_message=request.message,
            )
            timings["agent_chat_reply"] = 0.0

            reply = ChatMessage(role="assistant", text=reply_text)
            reply.metadata = build_reply_metadata(
                reply_kind="control",
                reply_source="control",
                playlist_changed=True,
                event_id=f"reply-{request.user_id}-control",
            )
            refreshed_session = synthesize_session_text(
                session=working_state.session,
                text=reply_text,
            )
            refreshed_session = append_session_event(
                refreshed_session,
                event_type="reply_generated",
                payload={
                    "reply_kind": reply.metadata.reply_kind,
                    "reply_source": reply.metadata.reply_source,
                    "playlist_changed": reply.metadata.playlist_changed,
                },
                event_id=reply.metadata.event_id,
            )
            save_station_session(
                StationSessionState(
                    session=refreshed_session,
                    chat_history=chat_history,
                    current_item=current_playlist_item(refreshed_session.playlist),
                )
            )
            working_state = StationSessionState(
                session=refreshed_session,
                chat_history=working_state.chat_history,
                current_item=working_state.current_item,
            )
            step_started_at = monotonic()
            append_chat_message(request.user_id, reply)
            timings["append_agent_reply"] = monotonic() - step_started_at

            timings["total"] = monotonic() - started_at
            LOGGER.info(
                "station_chat_timing user_id=%s route=%s regenerated=false timings=%s",
                request.user_id,
                route_label,
                {key: round(value, 3) for key, value in timings.items()},
            )
            return StationChatResponse(
                reply=reply,
                session=working_state.session,
                runtime=self.runtime_status(),
            )

        if not router.need_music:
            step_started_at = monotonic()
            reply_text = self._generate_dj_reply(
                session=seed_session,
                message=request.message,
                chat_history=chat_history,
            )
            timings["agent_chat_reply"] = monotonic() - step_started_at

            reply = ChatMessage(role="assistant", text=reply_text)
            reply.metadata = build_reply_metadata(
                reply_kind=_reply_kind_from_router(router),
                reply_source="agent",
                playlist_changed=False,
                event_id=f"reply-{request.user_id}-chat",
            )
            refreshed_session = synthesize_session_text(
                session=seed_session,
                text=reply_text,
            )
            refreshed_session = append_session_event(
                refreshed_session,
                event_type="reply_generated",
                payload={
                    "reply_kind": reply.metadata.reply_kind,
                    "reply_source": reply.metadata.reply_source,
                    "playlist_changed": reply.metadata.playlist_changed,
                },
                event_id=reply.metadata.event_id,
            )
            save_station_session(
                StationSessionState(
                    session=refreshed_session,
                    chat_history=chat_history,
                    current_item=current_playlist_item(refreshed_session.playlist),
                )
            )
            seed_session = refreshed_session
            step_started_at = monotonic()
            append_chat_message(request.user_id, reply)
            timings["append_agent_reply"] = monotonic() - step_started_at

            timings["total"] = monotonic() - started_at
            LOGGER.info(
                "station_chat_timing user_id=%s route=%s regenerated=false timings=%s",
                request.user_id,
                route_label,
                {key: round(value, 3) for key, value in timings.items()},
            )
            return StationChatResponse(
                reply=reply,
                session=seed_session,
                runtime=self.runtime_status(),
            )

        previous_user_state = (
            seed_session.program.context_snapshot.user_state
            if seed_session.program is not None
            else None
        )
        step_started_at = monotonic()
        generation = self._generation_service.generate(
            GenerateProgramRequest(
                user_id=request.user_id,
                device_context=request.device_context,
                user_state=(
                    previous_user_state.model_copy(
                        update={"free_text": build_router_request_text(request.message, router)}
                    )
                    if previous_user_state is not None
                    else {
                        "duration_minutes": 25,
                        "needs": ["companionship"],
                        "free_text": build_router_request_text(request.message, router),
                    }
                ),
                max_candidates=chat_regeneration_candidate_limit(
                    message=request.message,
                    router=router,
                ),
            ),
            chat_history=chat_history,
        )
        timings["collect_retune_candidates"] = monotonic() - step_started_at
        if requires_real_music_candidates(
            message=request.message,
            router=router,
        ) and not _has_real_music_candidates(generation.candidate_items):
            raise NoSuitableSongError(
                "没有找到符合这个需求的真实歌曲。可以换一个歌名、歌手，或把描述说得更具体一点。"
            )

        updated_session = retune_session_playlist(
            session=seed_session,
            message=request.message,
            router=router,
            program=generation.program,
            candidate_items=generation.candidate_items,
            generation_warnings=generation.warnings,
        )
        save_station_session(
            StationSessionState(
                session=updated_session,
                chat_history=chat_history,
                current_item=current_playlist_item(updated_session.playlist),
            )
        )
        timings["retune_playlist"] = monotonic() - step_started_at

        step_started_at = monotonic()
        reply_text = self._generate_dj_reply(
            session=updated_session,
            message=request.message,
            chat_history=chat_history,
        )
        timings["agent_chat_reply"] = monotonic() - step_started_at

        reply = ChatMessage(role="assistant", text=reply_text)
        reply.metadata = build_reply_metadata(
            reply_kind=_reply_kind_from_router(router),
            reply_source="agent",
            playlist_changed=True,
            event_id=f"reply-{request.user_id}-retune",
        )
        refreshed_session = synthesize_session_text(
            session=updated_session,
            text=reply_text,
        )
        refreshed_session = append_session_event(
            refreshed_session,
            event_type="reply_generated",
            payload={
                "reply_kind": reply.metadata.reply_kind,
                "reply_source": reply.metadata.reply_source,
                "playlist_changed": reply.metadata.playlist_changed,
            },
            event_id=reply.metadata.event_id,
        )
        save_station_session(
            StationSessionState(
                session=refreshed_session,
                chat_history=chat_history,
                current_item=current_playlist_item(refreshed_session.playlist),
            )
        )
        step_started_at = monotonic()
        append_chat_message(request.user_id, reply)
        timings["append_agent_reply"] = monotonic() - step_started_at

        step_started_at = monotonic()
        current_state = get_station_session(request.user_id)
        timings["reload_session"] = monotonic() - step_started_at
        if current_state is None:
            raise RuntimeError("station session is missing after chat update")

        timings["total"] = monotonic() - started_at
        LOGGER.info(
            "station_chat_timing user_id=%s route=%s regenerated=true timings=%s",
            request.user_id,
            route_label,
            {key: round(value, 3) for key, value in timings.items()},
        )
        return StationChatResponse(
            reply=reply,
            session=current_state.session,
            runtime=self.runtime_status(),
        )

    def now_playing(self, user_id: str) -> PlayerNowResponse:
        state = get_station_session(user_id)
        if state is None:
            return PlayerNowResponse(runtime=self.runtime_status())

        playlist = state.session.playlist
        if playlist is not None:
            queue = playlist.items
            current_item = current_playlist_item(playlist)
        elif state.session.program is not None:
            queue = [
                item
                for block in state.session.program.blocks
                for item in block.items
                if item.item_type != "narration"
            ]
            current_item = state.current_item or _first_playable_item(queue)
        else:
            queue = []
            current_item = None

        if current_item is not None:
            update_current_item(user_id, current_item)

        return PlayerNowResponse(
            session=state.session,
            current_item=current_item,
            queue=queue,
            playlist=playlist,
            runtime=self.runtime_status(),
        )

    def advance_player(
        self,
        user_id: str,
        request: PlayerAdvanceRequest,
    ) -> PlayerAdvanceResponse:
        with _generation_lock_for_user(user_id):
            return self._advance_player_unlocked(user_id=user_id, request=request)

    def _advance_player_unlocked(
        self,
        user_id: str,
        request: PlayerAdvanceRequest,
    ) -> PlayerAdvanceResponse:
        state = get_station_session(user_id)
        if state is None:
            return PlayerAdvanceResponse(runtime=self.runtime_status())

        playlist = state.session.playlist
        if playlist is None:
            now = self.now_playing(user_id)
            return PlayerAdvanceResponse(
                session=now.session,
                current_item=now.current_item,
                queue=now.queue,
                playlist=now.playlist,
                runtime=now.runtime,
            )

        current_before = current_playlist_item(playlist)
        if current_before is not None and request.item_id not in {None, current_before.item_id}:
            return PlayerAdvanceResponse(
                session=state.session,
                current_item=current_before,
                queue=playlist.items,
                playlist=playlist,
                runtime=self.runtime_status(),
                warnings=["Ignored stale playback advance request."],
            )

        advanced_playlist = advance_playlist(playlist, reason=request.reason)
        if current_before is not None and advanced_playlist.current_index != playlist.current_index:
            record_playlist_events(
                user_id=user_id,
                items=[current_before],
                event_type=request.reason.value,
            )

        warnings: list[str] = []
        if playlist_needs_refill(advanced_playlist):
            warnings.append("Playlist refill is needed and can be prepared in the background.")

        state = StationSessionState(
            session=state.session.model_copy(update={"playlist": advanced_playlist}),
            chat_history=state.chat_history,
            current_item=current_playlist_item(advanced_playlist),
        )
        save_station_session(state)

        current_item = current_playlist_item(advanced_playlist)
        if current_item is not None:
            update_current_item(user_id, current_item)

        return PlayerAdvanceResponse(
            session=state.session,
            current_item=current_item,
            queue=advanced_playlist.items,
            playlist=advanced_playlist,
            runtime=self.runtime_status(),
            warnings=warnings,
        )

    def refill_player(self, user_id: str) -> PlayerAdvanceResponse:
        with _generation_lock_for_user(user_id):
            state = get_station_session(user_id)
            if state is None:
                return PlayerAdvanceResponse(runtime=self.runtime_status())

            playlist = state.session.playlist
            if playlist is None:
                now = self.now_playing(user_id)
                return PlayerAdvanceResponse(
                    session=now.session,
                    current_item=now.current_item,
                    queue=now.queue,
                    playlist=now.playlist,
                    runtime=now.runtime,
                )

            if not playlist_needs_refill(playlist):
                current_item = current_playlist_item(playlist)
                return PlayerAdvanceResponse(
                    session=state.session,
                    current_item=current_item,
                    queue=playlist.items,
                    playlist=playlist,
                    runtime=self.runtime_status(),
                )

        generation, generation_warnings = self._generate_refill_candidates(
            state=state,
            message="",
            chat_history=state.chat_history,
        )

        with _generation_lock_for_user(user_id):
            latest_state = get_station_session(user_id)
            if latest_state is None:
                return PlayerAdvanceResponse(runtime=self.runtime_status())

            latest_playlist = latest_state.session.playlist
            if latest_playlist is None:
                now = self.now_playing(user_id)
                return PlayerAdvanceResponse(
                    session=now.session,
                    current_item=now.current_item,
                    queue=now.queue,
                    playlist=now.playlist,
                    runtime=now.runtime,
                    warnings=generation_warnings,
                )

            if not playlist_needs_refill(latest_playlist):
                current_item = current_playlist_item(latest_playlist)
                return PlayerAdvanceResponse(
                    session=latest_state.session,
                    current_item=current_item,
                    queue=latest_playlist.items,
                    playlist=latest_playlist,
                    runtime=self.runtime_status(),
                    warnings=generation_warnings,
                )

            state, warnings = self._apply_refill_generation(
                state=latest_state,
                generation=generation,
                generation_warnings=generation_warnings,
            )
            playlist = state.session.playlist or latest_playlist
            current_item = current_playlist_item(playlist)
            if current_item is not None:
                update_current_item(user_id, current_item)

            return PlayerAdvanceResponse(
                session=state.session,
                current_item=current_item,
                queue=playlist.items,
                playlist=playlist,
                runtime=self.runtime_status(),
                warnings=warnings,
            )

    def runtime_status(self) -> RuntimeStatus:
        return build_runtime_status()

    def _generate_refill_candidates(
        self,
        *,
        state: StationSessionState,
        message: str,
        chat_history: list[ChatMessage],
    ) -> tuple[GenerateProgramResponse | None, list[str]]:
        playlist = state.session.playlist
        if playlist is None or not playlist_needs_refill(playlist):
            return None, []

        if state.session.program is None:
            return None, ["Playlist refill skipped because session context is unavailable."]

        request = GenerateProgramRequest(
            user_id=state.session.user_id,
            device_context=state.session.program.context_snapshot.device_context,
            user_state=state.session.program.context_snapshot.user_state.model_copy(
                update={
                    "free_text": (
                        message or state.session.program.context_snapshot.user_state.free_text
                    )
                }
            ),
            max_candidates=playlist.target_size,
        )
        generation = self._generation_service.generate(
            request=request,
            chat_history=chat_history,
        )
        return generation, generation.warnings

    def _apply_refill_generation(
        self,
        *,
        state: StationSessionState,
        generation: GenerateProgramResponse | None,
        generation_warnings: list[str],
    ) -> tuple[StationSessionState, list[str]]:
        playlist = state.session.playlist
        if playlist is None or not playlist_needs_refill(playlist):
            return state, generation_warnings
        if generation is None:
            return state, generation_warnings

        return apply_refill_generation_to_state(
            state=state,
            program=generation.program,
            candidate_items=generation.candidate_items,
            generation_warnings=generation_warnings,
        )

    def _plan_chat_turn_with_fallback(
        self,
        *,
        session: StationSession,
        message: str,
        chat_history: list[ChatMessage],
    ) -> ChatRouterResult:
        try:
            return self._runtime.plan_chat_turn(
                session=session,
                message=message,
                chat_history=chat_history,
            )
        except Exception as exc:
            LOGGER.warning(
                "station_chat_router_failed user_id=%s error=%s",
                session.user_id,
                exc,
            )
            return fallback_chat_router_result(message)

    def _generate_dj_reply(
        self,
        *,
        session: StationSession,
        message: str,
        chat_history: list[ChatMessage],
    ) -> str:
        try:
            reply = self._runtime.generate_chat_reply(
                session=session,
                message=message,
                chat_history=chat_history,
            )
        except Exception as exc:
            LOGGER.warning(
                "station_dj_reply_failed user_id=%s error=%s",
                session.user_id,
                exc,
            )
            raise AgentOutputValidationError(f"LLM chat reply failed: {exc}") from exc
        return compact_agent_reply(reply, fallback_message=message)

    def _apply_chat_control(
        self,
        *,
        state: StationSessionState,
        chat_history: list[ChatMessage],
        router: ChatRouterResult,
        message: str,
    ) -> tuple[StationSessionState, str]:
        return apply_chat_control(
            state=state,
            chat_history=chat_history,
            router=router,
            message=message,
        )


def _first_playable_item(items: list[ProgramItem]) -> ProgramItem | None:
    for item in items:
        if item.item_type != "narration":
            return item
    return None


def _has_real_music_candidates(candidate_items: object) -> bool:
    if not isinstance(candidate_items, list):
        return False
    return any(
        getattr(candidate, "content_type", None) == "music"
        and not str(getattr(candidate, "source", "")).lower().startswith("mock")
        for candidate in candidate_items
    )


def _opening_narration(program: object) -> str | None:
    blocks = getattr(program, "blocks", [])
    for block in blocks:
        for item in block.items:
            if item.item_type != "narration":
                continue
            if item.narration_text:
                return item.narration_text.strip()
    return None


def _generation_lock_for_user(user_id: str) -> Lock:
    with _LOCKS_LOCK:
        lock = _USER_GENERATION_LOCKS.get(user_id)
        if lock is None:
            lock = Lock()
            _USER_GENERATION_LOCKS[user_id] = lock
        return lock


def _reply_kind_from_router(router: ChatRouterResult) -> str:
    if router.need_control:
        return "control"
    if router.need_info and not router.need_music:
        return "info"
    if router.need_music:
        return "music"
    return "chat"
