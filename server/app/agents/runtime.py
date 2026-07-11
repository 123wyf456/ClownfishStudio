from app.agents.prompts import (
    build_chat_turn_prompt,
    build_radio_prompt,
    build_station_chat_reply_prompt,
    build_station_greeting_prompt,
)
from app.agents.radio_agent import (
    AnthropicRadioModelClient,
    OpenAIResponsesRadioModelClient,
    RadioAgentInput,
    RadioModelClient,
)
from app.core.config import get_settings
from app.schemas import (
    CalendarEvent,
    CandidateItem,
    ChatMessage,
    ChatRouterResult,
    ContentType,
    ContextSnapshot,
    GenerateProgramRequest,
    ProgramItem,
    ProgramItemType,
    RadioProgram,
    StationSession,
    UserMusicMemory,
)


class AgentOutputValidationError(ValueError):
    pass


class RadioAgentRuntime:
    def __init__(self, model_client: RadioModelClient | None = None) -> None:
        self._model_client = model_client or _build_default_model_client()

    def generate_program(
        self,
        request: GenerateProgramRequest,
        weather: dict[str, str | int | float | bool | None],
        calendar_events: list[CalendarEvent],
        memory: UserMusicMemory,
        history: list[dict[str, str]],
        candidate_items: list[CandidateItem],
        chat_history: list[ChatMessage] | None = None,
    ) -> RadioProgram:
        if not candidate_items:
            raise AgentOutputValidationError(
                "RadioAgentRuntime requires at least one candidate item"
            )

        context_snapshot = ContextSnapshot(
            device_context=request.device_context,
            user_state=request.user_state,
            weather=weather,
            calendar_events=calendar_events,
        )
        prompt = build_radio_prompt(
            context_snapshot=context_snapshot,
            memory=memory,
            history=history,
            candidate_items=candidate_items,
            chat_history=chat_history,
        )
        agent_input = RadioAgentInput(
            request=request,
            context_snapshot=context_snapshot,
            memory=memory,
            history=history,
            candidate_items=candidate_items,
            chat_history=list(chat_history or []),
            prompt=prompt,
        )
        raw_program = self._model_client.generate_program(agent_input)
        program = RadioProgram.model_validate(raw_program)
        self._validate_candidate_references(program=program, candidate_items=candidate_items)
        return self._hydrate_program_items(program=program, candidate_items=candidate_items)

    def generate_greeting(
        self,
        *,
        program: RadioProgram,
        chat_history: list[ChatMessage] | None = None,
    ) -> str:
        prompt = build_station_greeting_prompt(
            request_context=program.context_snapshot,
            program=program,
            chat_history=chat_history,
        )
        return self._model_client.generate_short_text(prompt)

    def generate_chat_reply(
        self,
        *,
        session: StationSession,
        message: str,
        chat_history: list[ChatMessage] | None = None,
    ) -> str:
        prompt = build_station_chat_reply_prompt(
            session=session,
            message=message,
            chat_history=chat_history,
        )
        return self._model_client.generate_short_text(prompt)

    def plan_chat_turn(
        self,
        *,
        session: StationSession,
        message: str,
        chat_history: list[ChatMessage] | None = None,
    ) -> ChatRouterResult:
        prompt = build_chat_turn_prompt(
            session=session,
            message=message,
            chat_history=chat_history,
        )
        return self._model_client.plan_chat_turn(prompt)

    def _validate_candidate_references(
        self,
        program: RadioProgram,
        candidate_items: list[CandidateItem],
    ) -> None:
        candidates_by_id = {candidate.candidate_id: candidate for candidate in candidate_items}

        for block in program.blocks:
            for item in block.items:
                if item.item_type is ProgramItemType.narration:
                    continue

                if item.candidate_id not in candidates_by_id:
                    raise AgentOutputValidationError(
                        f"program item {item.item_id} references unknown candidate_id "
                        f"{item.candidate_id}"
                    )

                candidate = candidates_by_id[item.candidate_id]
                if (
                    item.item_type is ProgramItemType.music
                    and candidate.content_type is not ContentType.music
                ):
                    raise AgentOutputValidationError(
                        f"program item {item.item_id} references non-music candidate "
                        f"{candidate.candidate_id}"
                    )

                if (
                    item.item_type is ProgramItemType.podcast
                    and candidate.content_type is not ContentType.podcast
                ):
                    raise AgentOutputValidationError(
                        f"program item {item.item_id} references non-podcast candidate "
                        f"{candidate.candidate_id}"
                    )

    def _hydrate_program_items(
        self,
        program: RadioProgram,
        candidate_items: list[CandidateItem],
    ) -> RadioProgram:
        candidates_by_id = {candidate.candidate_id: candidate for candidate in candidate_items}
        hydrated_blocks = []

        for block in program.blocks:
            hydrated_items = [
                self._hydrate_program_item(item=item, candidates_by_id=candidates_by_id)
                for item in block.items
            ]
            hydrated_blocks.append(block.model_copy(update={"items": hydrated_items}))

        return program.model_copy(update={"blocks": hydrated_blocks})

    def _hydrate_program_item(
        self,
        item: ProgramItem,
        candidates_by_id: dict[str, CandidateItem],
    ) -> ProgramItem:
        if item.item_type is ProgramItemType.narration or item.candidate_id is None:
            return item

        candidate = candidates_by_id[item.candidate_id]
        return item.model_copy(
            update={
                "title": candidate.title,
                "creator": candidate.creator,
                "playback_url": candidate.playback_url,
                "duration_seconds": candidate.duration_seconds,
            }
        )


def _build_default_model_client() -> RadioModelClient:
    settings = get_settings()
    if settings.radio_agent_provider == "anthropic":
        if not settings.anthropic_api_key:
            raise AgentOutputValidationError(
                "RADIO_AGENT_PROVIDER is configured for Anthropic but its API key is missing"
            )
        return AnthropicRadioModelClient(
            api_key=settings.anthropic_api_key,
            model=settings.radio_agent_model,
            base_url=settings.anthropic_base_url,
        )

    if not settings.openai_api_key:
        raise AgentOutputValidationError(
            "RADIO_AGENT_PROVIDER is configured for OpenAI-compatible mode "
            "but its API key is missing"
        )

    return OpenAIResponsesRadioModelClient(
        api_key=settings.openai_api_key,
        model=settings.radio_agent_model,
        base_url=settings.openai_base_url,
        prefer_chat_completions=True,
    )
