from __future__ import annotations

import re
from uuid import uuid4

from app.agents import RadioAgentRuntime
from app.schemas import (
    ChatMessage,
    GenerateProgramRequest,
    PlayerNowResponse,
    ProgramItem,
    RuntimeStatus,
    StationChatRequest,
    StationChatResponse,
    StationGenerateResponse,
    StationSession,
)
from app.services.program_generation import ProgramGenerationService
from app.services.providers import (
    build_calendar_provider,
    build_runtime_status,
    build_tts_provider,
    build_weather_provider,
)
from app.services.session_store import (
    StationSessionState,
    append_chat_message,
    get_station_session,
    save_station_session,
    update_current_item,
)


class StationOrchestrator:
    def __init__(
        self,
        runtime: RadioAgentRuntime | None = None,
    ) -> None:
        self._runtime = runtime or RadioAgentRuntime()
        self._generation_service = ProgramGenerationService(runtime=self._runtime)
        self._weather_provider = build_weather_provider()
        self._calendar_provider = build_calendar_provider()
        self._tts_provider = build_tts_provider()

    def generate_station(self, request: GenerateProgramRequest) -> StationGenerateResponse:
        generation = self._generation_service.generate(request)
        weather = self._weather_provider.get_weather(request.device_context.city_hint)
        calendar_events = self._calendar_provider.get_events(request.user_id)
        greeting = self._build_greeting(
            city=weather.get("city"),
            condition=weather.get("condition"),
            title=generation.program.title,
            locale=request.device_context.locale,
            request_text=request.user_state.free_text,
        )
        tts_audio_url, tts_text = self._tts_provider.synthesize(greeting)
        session_warnings = [*generation.warnings]
        if tts_text and tts_audio_url is None:
            session_warnings.append(
                "TTS audio is unavailable for this session; returning text only."
            )
        session = StationSession(
            session_id=f"session-{uuid4().hex}",
            user_id=request.user_id,
            greeting=greeting,
            tts_text=tts_text,
            tts_audio_url=tts_audio_url,
            program=generation.program.model_copy(
                update={
                    "context_snapshot": generation.program.context_snapshot.model_copy(
                        update={"calendar_events": calendar_events, "weather": weather}
                    )
                }
            ),
            weather=weather,
            calendar_events=calendar_events,
            warnings=session_warnings,
        )
        current_item = _first_playable_item(session.program.blocks[0].items)
        save_station_session(
            StationSessionState(
                session=session,
                current_item=current_item,
            )
        )

        return StationGenerateResponse(
            session=session,
            candidate_count=generation.candidate_count,
            runtime=self.runtime_status(),
        )

    def chat(self, request: StationChatRequest) -> StationChatResponse:
        state = get_station_session(request.user_id)
        if state is None:
            session_response = self.generate_station(
                GenerateProgramRequest(
                    user_id=request.user_id,
                    device_context=request.device_context,
                    user_state={
                        "duration_minutes": 25,
                        "needs": ["companionship"],
                        "free_text": request.message,
                    },
                )
            )
            reply_text = self._build_chat_reply(session_response.session, request.message)
            append_chat_message(request.user_id, ChatMessage(role="user", text=request.message))
            reply = ChatMessage(role="assistant", text=reply_text)
            append_chat_message(request.user_id, reply)
            current_state = get_station_session(request.user_id)
            if current_state is None:
                raise RuntimeError("station session was not created")
            return StationChatResponse(
                reply=reply,
                session=current_state.session,
                runtime=self.runtime_status(),
            )

        seed_session = state.session

        user_message = ChatMessage(role="user", text=request.message)
        append_chat_message(request.user_id, user_message)
        previous_user_state = seed_session.program.context_snapshot.user_state
        regenerated = self.generate_station(
            GenerateProgramRequest(
                user_id=request.user_id,
                device_context=request.device_context,
                user_state=previous_user_state.model_copy(
                    update={"free_text": request.message.strip()}
                ),
            )
        )
        reply_text = self._build_chat_reply(regenerated.session, request.message)
        reply = ChatMessage(role="assistant", text=reply_text)
        append_chat_message(request.user_id, reply)
        current_state = get_station_session(request.user_id)
        if current_state is None:
            raise RuntimeError("station session is missing after chat update")

        return StationChatResponse(
            reply=reply,
            session=current_state.session,
            runtime=self.runtime_status(),
        )

    def now_playing(self, user_id: str) -> PlayerNowResponse:
        state = get_station_session(user_id)
        if state is None:
            return PlayerNowResponse(runtime=self.runtime_status())

        queue = [
            item
            for block in state.session.program.blocks
            for item in block.items
            if item.item_type != "narration"
        ]
        current_item = state.current_item or _first_playable_item(queue)
        if current_item is not None:
            update_current_item(user_id, current_item)

        return PlayerNowResponse(
            session=state.session,
            current_item=current_item,
            queue=queue,
            runtime=self.runtime_status(),
        )

    def runtime_status(self) -> RuntimeStatus:
        return build_runtime_status()

    def _build_greeting(
        self,
        city: object,
        condition: object,
        title: str,
        locale: str | None,
        request_text: str | None,
    ) -> str:
        del city
        if (
            _prefer_chinese(request_text or "")
            or (isinstance(locale, str) and locale.lower().startswith("zh"))
            or _prefer_chinese(title)
        ):
            condition_text = condition.strip() if isinstance(condition, str) and condition.strip() else "今晚"
            return f"这里是《{title}》。先陪你把频道调稳，今夜的底色会更偏向{condition_text}一点。"

        return f"Welcome to {title}. I tuned the opening gently, so the station can settle in with you."

    def _build_chat_reply(self, session: StationSession, message: str) -> str:
        lead = session.program.blocks[0].title if session.program.blocks else session.program.title
        clean_message = message.strip()
        if _prefer_chinese(clean_message):
            return f"收到，关于“{clean_message}”，我已经把后面的节目重新收拢，会更贴近你刚才说的感觉。"
        return f"Got it. I retuned the next stretch around {lead}, so it stays closer to what you asked for."


def _first_playable_item(items: list[ProgramItem]) -> ProgramItem | None:
    for item in items:
        if item.item_type != "narration":
            return item
    return None


def _prefer_chinese(value: str) -> bool:
    if not value:
        return False
    chinese_count = len(re.findall(r"[\u4e00-\u9fff]", value))
    ascii_word_count = len(re.findall(r"[A-Za-z]{2,}", value))
    return chinese_count > 0 and chinese_count >= ascii_word_count

