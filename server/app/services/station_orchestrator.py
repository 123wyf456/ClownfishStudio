from __future__ import annotations

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
            state = get_station_session(request.user_id)
            if state is None:
                raise RuntimeError("station session was not created")
            seed_session = session_response.session
        else:
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
    ) -> str:
        city_text = city.strip() if isinstance(city, str) and city.strip() else "your city"
        condition_text = (
            condition.strip() if isinstance(condition, str) and condition.strip() else "tonight"
        )
        return (
            f"Welcome to {title}. {city_text} feels a little like {condition_text} right now, "
            "so we will start with something gentle."
        )

    def _build_chat_reply(self, session: StationSession, message: str) -> str:
        lead = session.program.blocks[0].title if session.program.blocks else session.program.title
        return (
            f"I heard you: {message.strip()}. Next I will keep shaping the station around "
            f"{lead} so it stays closer to what you need right now."
        )


def _first_playable_item(items: list[ProgramItem]) -> ProgramItem | None:
    for item in items:
        if item.item_type != "narration":
            return item
    return None

