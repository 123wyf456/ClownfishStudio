from __future__ import annotations

import hashlib
import logging
import re
from threading import Lock
from time import monotonic
from uuid import uuid4

from app.agents import RadioAgentRuntime
from app.schemas import (
    CandidateItem,
    ChatMessage,
    GenerateProgramRequest,
    GenerateProgramResponse,
    PlayerAdvanceRequest,
    PlayerAdvanceResponse,
    PlayerNowResponse,
    PlaylistItemSource,
    ProgramItem,
    RadioProgram,
    RuntimeStatus,
    StationChatRequest,
    StationChatResponse,
    StationGenerateResponse,
    StationSession,
)
from app.services.playlist_runtime import (
    advance_playlist,
    create_playlist_from_candidates,
    current_playlist_item,
    playlist_needs_refill,
    record_playlist_events,
    refill_playlist,
    retune_playlist_after_current,
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

LOGGER = logging.getLogger(__name__)
_LOCKS_LOCK = Lock()
_USER_GENERATION_LOCKS: dict[str, Lock] = {}


class NoSuitableSongError(RuntimeError):
    pass


class StationOrchestrator:
    def __init__(
        self,
        runtime: RadioAgentRuntime | None = None,
    ) -> None:
        self._runtime = runtime or RadioAgentRuntime()
        self._generation_service = ProgramGenerationService(runtime=self._runtime)

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

        weather = generation.program.context_snapshot.weather
        calendar_events = generation.program.context_snapshot.calendar_events

        step_started_at = monotonic()
        greeting = _compact_agent_reply(
            _opening_narration(generation.program) or generation.program.summary,
            fallback_message=request.user_state.free_text or "",
        )
        timings["derive_greeting"] = monotonic() - step_started_at

        session_warnings = [*generation.warnings]
        selected_candidates = _program_music_candidates(
            program=generation.program,
            candidate_items=generation.candidate_items,
        )
        if not selected_candidates:
            selected_candidates = _music_candidates(generation.candidate_items)
        playlist = create_playlist_from_candidates(
            selected_candidates,
            inserted_by=PlaylistItemSource.initial,
        )
        if len(playlist.items) < playlist.target_size:
            session_warnings.append(
                "Only part of the initial playlist could be filled with playable music."
            )

        session = StationSession(
            session_id=f"session-{uuid4().hex}",
            user_id=request.user_id,
            greeting=greeting,
            tts_text=None,
            tts_audio_url=None,
            program=generation.program.model_copy(
                update={
                    "context_snapshot": generation.program.context_snapshot.model_copy(
                        update={"calendar_events": calendar_events, "weather": weather}
                    )
                }
            ),
            playlist=playlist,
            weather=weather,
            calendar_events=calendar_events,
            warnings=session_warnings,
        )
        current_item = current_playlist_item(playlist)

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
            session_response = self._generate_station_unlocked(
                GenerateProgramRequest(
                    user_id=request.user_id,
                    device_context=request.device_context,
                    user_state={
                        "duration_minutes": 25,
                        "needs": ["companionship"],
                        "free_text": request.message,
                    },
                    max_candidates=8,
                ),
                chat_history=[user_message],
            )

            step_started_at = monotonic()
            append_chat_message(request.user_id, user_message)
            chat_history = list_chat_history(request.user_id)
            timings["append_user_message"] = monotonic() - step_started_at

            reply_text = _compact_agent_reply(
                session_response.session.greeting,
                fallback_message=request.message,
            )
            timings["agent_chat_reply"] = 0.0

            reply = ChatMessage(role="assistant", text=reply_text)
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
                "station_chat_timing user_id=%s created_session=true timings=%s",
                request.user_id,
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
        chat_turn = self._plan_chat_turn_with_fallback(
            session=seed_session,
            message=request.message,
            chat_history=chat_history,
        )
        intent = chat_turn.role
        timings["agent_intent"] = monotonic() - step_started_at

        if intent in {"chat_only", "config_help"}:
            reply_text = _compact_agent_reply(
                chat_turn.text,
                fallback_message=request.message,
            )
            timings["agent_chat_reply"] = 0.0

            reply = ChatMessage(role="assistant", text=reply_text)
            step_started_at = monotonic()
            append_chat_message(request.user_id, reply)
            timings["append_agent_reply"] = monotonic() - step_started_at

            timings["total"] = monotonic() - started_at
            LOGGER.info(
                "station_chat_timing user_id=%s intent=%s regenerated=false timings=%s",
                request.user_id,
                intent,
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
                    previous_user_state.model_copy(update={"free_text": request.message.strip()})
                    if previous_user_state is not None
                    else {
                        "duration_minutes": 25,
                        "needs": ["companionship"],
                        "free_text": request.message.strip(),
                    }
                ),
                max_candidates=_chat_regeneration_candidate_limit(intent),
            ),
            chat_history=chat_history,
        )
        timings["collect_retune_candidates"] = monotonic() - step_started_at
        if intent == "song_request" and not _has_real_music_candidates(
            generation.candidate_items
        ):
            raise NoSuitableSongError(
                "没有找到符合这个需求的真实歌曲。可以换一个歌名、歌手，或把描述说得更具体一点。"
            )

        playlist = seed_session.playlist
        if playlist is None:
            playlist = create_playlist_from_candidates(
                _program_music_candidates(
                    program=generation.program,
                    candidate_items=generation.candidate_items,
                ),
                inserted_by=PlaylistItemSource.user_request,
            )
            mutation_warnings: list[str] = []
        else:
            mutation = retune_playlist_after_current(
                playlist,
                _program_music_candidates(
                    program=generation.program,
                    candidate_items=generation.candidate_items,
                ),
            )
            playlist = mutation.playlist
            mutation_warnings = mutation.warnings
            if mutation.dropped_items:
                record_playlist_events(
                    user_id=request.user_id,
                    items=mutation.dropped_items,
                    event_type="dropped",
                )
            if mutation.inserted_items:
                record_playlist_events(
                    user_id=request.user_id,
                    items=mutation.inserted_items,
                    event_type="inserted",
                )

        updated_session = seed_session.model_copy(
            update={
                "greeting": _compact_agent_reply(
                    chat_turn.text,
                    fallback_message=request.message,
                ),
                "playlist": playlist,
                "warnings": [
                    *seed_session.warnings,
                    *generation.warnings,
                    *mutation_warnings,
                ],
            }
        )
        save_station_session(
            StationSessionState(
                session=updated_session,
                chat_history=chat_history,
                current_item=current_playlist_item(playlist),
            )
        )
        timings["retune_playlist"] = monotonic() - step_started_at

        reply_text = _compact_agent_reply(
            chat_turn.text,
            fallback_message=request.message,
        )
        timings["agent_chat_reply"] = 0.0

        reply = ChatMessage(role="assistant", text=reply_text)
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
            "station_chat_timing user_id=%s intent=%s regenerated=true timings=%s",
            request.user_id,
            intent,
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

        playlist = advanced_playlist
        state = StationSessionState(
            session=state.session.model_copy(update={"playlist": playlist}),
            chat_history=state.chat_history,
            current_item=current_playlist_item(playlist),
        )

        save_station_session(state)

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

        mutation = refill_playlist(
            playlist,
            _program_music_candidates(
                program=generation.program,
                candidate_items=generation.candidate_items,
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

    def _plan_chat_turn_with_fallback(
        self,
        *,
        session: StationSession,
        message: str,
        chat_history: list[ChatMessage],
    ) -> ChatMessage:
        try:
            decision = self._runtime.plan_chat_turn(
                session=session,
                message=message,
                chat_history=chat_history,
            )
            return ChatMessage(role=decision.intent, text=decision.reply_text)
        except Exception as exc:
            LOGGER.warning(
                "station_chat_turn_failed user_id=%s error=%s",
                session.user_id,
                exc,
            )
            intent = _classify_chat_intent(message)
            return ChatMessage(
                role=intent,
                text=_fallback_chat_reply(message=message, intent=intent),
            )


def _first_playable_item(items: list[ProgramItem]) -> ProgramItem | None:
    for item in items:
        if item.item_type != "narration":
            return item
    return None


def _program_music_candidates(
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

    if len(selected_candidates) >= min(8, len(_music_candidates(candidate_items))):
        return selected_candidates

    selected_candidates.extend(
        candidate
        for candidate in _music_candidates(candidate_items)
        if candidate.candidate_id not in seen_candidate_ids
    )
    return selected_candidates


def _music_candidates(candidate_items: list[CandidateItem]) -> list[CandidateItem]:
    return [candidate for candidate in candidate_items if candidate.content_type == "music"]


def _has_real_music_candidates(candidate_items: list[CandidateItem]) -> bool:
    return any(
        candidate.content_type == "music" and not candidate.source.lower().startswith("mock")
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


def _classify_chat_intent(message: str) -> str:
    text = message.strip().lower()
    if not text:
        return "chat_only"

    if _contains_any(
        text,
        [
            "api key",
            "apikey",
            "配置",
            "设置",
            "key",
            "netease",
            "网易云",
            "anthropic",
            "fish audio",
        ],
    ):
        return "config_help"

    if _contains_any(
        text,
        [
            "播放",
            "来点",
            "来一首",
            "想听",
            "推荐",
            "歌手",
            "这首",
            "歌曲",
            "music",
            "song",
            "artist",
            "play ",
            "listen to",
            "recommend",
        ],
    ):
        return "song_request"

    if _contains_any(
        text,
        [
            "换",
            "重生成",
            "重新生成",
            "重新",
            "调整",
            "调成",
            "更安静",
            "更热闹",
            "更轻松",
            "不要播客",
            "regenerate",
            "retune",
            "change",
            "make it",
            "no podcast",
        ],
    ):
        return "retune_program"

    return "chat_only"


def _contains_any(text: str, values: list[str]) -> bool:
    return any(value in text for value in values)


def _fallback_chat_reply(message: str, intent: str) -> str:
    if _prefer_chinese(message):
        variants = {
            "config_help": ["可以，我先看配置。", "好，我们先理顺设置。"],
            "song_request": ["好，我按这个方向找歌。", "这个口味我接住了。"],
            "retune_program": ["好，后面我换个走向。", "嗯，我把节奏调一下。"],
            "chat_only": ["我在，先陪你听着。", "嗯，我们慢慢来。"],
        }
    else:
        variants = {
            "config_help": ["Sure, I will check setup first.", "Let us sort settings first."],
            "song_request": [
                "Got it, I will look that way.",
                "I hear the taste; next set follows.",
            ],
            "retune_program": ["Okay, I will shift the next stretch.", "I will retune the pacing."],
            "chat_only": ["I am here; we can keep listening.", "Yeah, let us take it slowly."],
        }
    return _stable_variant(variants.get(intent) or variants["chat_only"], f"{intent}:{message}")


def _prefer_chinese(value: str) -> bool:
    chinese_count = len(re.findall(r"[\u4e00-\u9fff]", value))
    ascii_word_count = len(re.findall(r"[A-Za-z]{2,}", value))
    return chinese_count > 0 and chinese_count >= ascii_word_count


def _compact_agent_reply(text: str, fallback_message: str) -> str:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return _fallback_chat_reply(message=fallback_message, intent="chat_only")
    if _prefer_chinese(fallback_message) and not _prefer_chinese(normalized):
        return _fallback_chat_reply(message=fallback_message, intent="chat_only")

    first_sentence = re.split(r"(?<=[。！？.!?])\s*", normalized, maxsplit=1)[0].strip()
    if first_sentence:
        normalized = first_sentence

    prefer_chinese = _prefer_chinese(fallback_message) or _prefer_chinese(normalized)
    limit = 36 if prefer_chinese else 96
    if len(normalized) <= limit:
        return normalized
    suffix = "。" if prefer_chinese else "."
    return normalized[:limit].rstrip("，。！？,.!? ") + suffix


def _stable_variant(values: list[str], seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()
    return values[int(digest[:8], 16) % len(values)]


def _chat_regeneration_candidate_limit(intent: str) -> int:
    if intent == "song_request":
        return 8
    return 10


def _generation_lock_for_user(user_id: str) -> Lock:
    with _LOCKS_LOCK:
        lock = _USER_GENERATION_LOCKS.get(user_id)
        if lock is None:
            lock = Lock()
            _USER_GENERATION_LOCKS[user_id] = lock
        return lock
