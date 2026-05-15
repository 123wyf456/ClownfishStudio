import json
from datetime import UTC, datetime

import pytest

from app.agents import (
    AgentOutputValidationError,
    AnthropicRadioModelClient,
    OpenAIResponsesRadioModelClient,
    RadioAgentInput,
    RadioAgentRuntime,
)
from app.schemas import (
    ChatMessage,
    ContentType,
    DeviceContext,
    GenerateProgramRequest,
    ProgramItemType,
    UserStateInput,
)
from app.tools import (
    get_recent_history,
    get_user_music_memory,
    get_weather,
    search_music_candidates,
    search_podcast_candidates,
)


def test_runtime_generates_program_from_tool_candidates() -> None:
    request = make_request()
    candidate_items = search_music_candidates(limit=4) + search_podcast_candidates(limit=2)
    runtime = RadioAgentRuntime()

    program = runtime.generate_program(
        request=request,
        weather=get_weather("Shanghai"),
        calendar_events=[],
        memory=get_user_music_memory("demo-user"),
        history=get_recent_history("demo-user"),
        candidate_items=candidate_items,
    )

    selected_candidate_ids = {
        item.candidate_id
        for block in program.blocks
        for item in block.items
        if item.item_type is not ProgramItemType.narration
    }
    available_candidate_ids = {candidate.candidate_id for candidate in candidate_items}

    assert program.context_snapshot.device_context.city_hint == "Shanghai"
    assert selected_candidate_ids
    assert selected_candidate_ids.issubset(available_candidate_ids)
    assert "podcast-1" not in selected_candidate_ids


def test_mock_agent_writes_concise_narration_and_track_explanations() -> None:
    request = make_request()
    candidate_items = search_music_candidates(limit=4) + search_podcast_candidates(limit=2)
    runtime = RadioAgentRuntime()

    program = runtime.generate_program(
        request=request,
        weather=get_weather("Shanghai"),
        calendar_events=[],
        memory=get_user_music_memory("demo-user"),
        history=get_recent_history("demo-user"),
        candidate_items=candidate_items,
    )

    opening = program.blocks[0].items[0]
    playable_items = [
        item
        for block in program.blocks
        for item in block.items
        if item.item_type is not ProgramItemType.narration
    ]
    bridge_items = [
        item
        for block in program.blocks
        for item in block.items
        if item.item_type is ProgramItemType.narration and item.position > 0
    ]

    assert opening.item_type is ProgramItemType.narration
    assert opening.narration_text is not None
    assert "Clownfish" in opening.narration_text
    assert len(opening.narration_text) <= 80
    assert "Shanghai" not in opening.narration_text
    assert playable_items[0].title not in opening.narration_text
    assert bridge_items
    assert all(item.explanation for item in playable_items)


def test_runtime_rejects_model_output_with_unknown_candidate_id() -> None:
    runtime = RadioAgentRuntime(model_client=UnknownCandidateModelClient())

    with pytest.raises(AgentOutputValidationError, match="unknown candidate_id"):
        runtime.generate_program(
            request=make_request(),
            weather=get_weather("Shanghai"),
            calendar_events=[],
            memory=get_user_music_memory("demo-user"),
            history=[],
            candidate_items=search_music_candidates(limit=1),
        )


def test_runtime_hydrates_playable_fields_from_candidate_items() -> None:
    candidate_items = search_music_candidates(limit=1)
    runtime = RadioAgentRuntime(model_client=LyingTitleModelClient())

    program = runtime.generate_program(
        request=make_request(),
        weather=get_weather("Shanghai"),
        calendar_events=[],
        memory=get_user_music_memory("demo-user"),
        history=[],
        candidate_items=candidate_items,
    )

    playable_item = program.blocks[0].items[1]
    assert playable_item.title == candidate_items[0].title
    assert playable_item.playback_url == candidate_items[0].playback_url


def test_openai_client_uses_structured_outputs_and_server_owned_fields() -> None:
    candidate_items = search_music_candidates(limit=1)
    model_client = CapturingOpenAIModelClient()
    runtime = RadioAgentRuntime(model_client=model_client)

    program = runtime.generate_program(
        request=make_request(),
        weather=get_weather("Shanghai"),
        calendar_events=[],
        memory=get_user_music_memory("demo-user"),
        history=[],
        candidate_items=candidate_items,
        chat_history=[ChatMessage(role="user", text="想听更安静一点")],
    )

    assert model_client.path == "/responses"
    assert model_client.body is not None
    text_format = model_client.body["text"]["format"]
    assert text_format["type"] == "json_schema"
    assert text_format["strict"] is True
    assert text_format["schema"]["required"] == ["title", "summary", "blocks"]
    assert program.program_id.startswith("program-")
    assert program.context_snapshot.device_context.city_hint == "Shanghai"
    assert program.blocks[0].items[1].candidate_id == candidate_items[0].candidate_id
    user_prompt = model_client.body["input"][1]["content"][0]["text"]
    assert "Recent chat history:" in user_prompt
    assert "想听更安静一点" in user_prompt


def test_anthropic_client_uses_messages_api_and_server_owned_fields() -> None:
    candidate_items = search_music_candidates(limit=1)
    model_client = CapturingAnthropicModelClient()
    runtime = RadioAgentRuntime(model_client=model_client)

    program = runtime.generate_program(
        request=make_request(),
        weather=get_weather("Shanghai"),
        calendar_events=[],
        memory=get_user_music_memory("demo-user"),
        history=[],
        candidate_items=candidate_items,
    )

    assert model_client.path == "/v1/messages"
    assert model_client.body is not None
    assert model_client.body["model"] == "claude-test"
    assert model_client.body["messages"][0]["role"] == "user"
    assert "Return only one JSON object" in model_client.body["system"]
    assert program.program_id.startswith("program-")
    assert program.blocks[0].items[1].candidate_id == candidate_items[0].candidate_id


def test_runtime_normalizes_flat_model_items_into_program_blocks() -> None:
    candidate_items = search_music_candidates(limit=1) + search_podcast_candidates(limit=1)
    runtime = RadioAgentRuntime(model_client=FlatItemsOpenAIModelClient())

    program = runtime.generate_program(
        request=make_request(),
        weather=get_weather("Shanghai"),
        calendar_events=[],
        memory=get_user_music_memory("demo-user"),
        history=[],
        candidate_items=candidate_items,
    )

    assert len(program.blocks) == 1
    assert program.blocks[0].title == "Flat Draft"
    assert [item.item_type for item in program.blocks[0].items] == [
        ProgramItemType.narration,
        ProgramItemType.music,
        ProgramItemType.narration,
        ProgramItemType.podcast,
    ]
    assert program.blocks[0].items[1].candidate_id == "music-1"
    assert program.blocks[0].items[1].title == candidate_items[0].title
    assert program.blocks[0].items[3].candidate_id == "podcast-1"


def make_request() -> GenerateProgramRequest:
    return GenerateProgramRequest(
        user_id="demo-user",
        device_context=DeviceContext(
            local_time=datetime(2026, 4, 30, 22, 30, tzinfo=UTC),
            timezone="Asia/Shanghai",
            city_hint="Shanghai",
        ),
        user_state=UserStateInput(duration_minutes=25, free_text="今天想恢复一点精力。"),
    )


class UnknownCandidateModelClient:
    def generate_program(self, agent_input: RadioAgentInput) -> dict[str, object]:
        return make_raw_program(agent_input=agent_input, candidate_id="missing-candidate")


class LyingTitleModelClient:
    def generate_program(self, agent_input: RadioAgentInput) -> dict[str, object]:
        return make_raw_program(
            agent_input=agent_input,
            candidate_id=agent_input.candidate_items[0].candidate_id,
            title="Fabricated Title",
            playback_url="mock://fabricated",
        )


class CapturingOpenAIModelClient(OpenAIResponsesRadioModelClient):
    def __init__(self) -> None:
        super().__init__(api_key="test-key", model="test-model")
        self.path: str | None = None
        self.body: dict[str, object] | None = None

    def _post_json(self, path: str, body: dict[str, object]) -> dict[str, object]:
        self.path = path
        self.body = body
        return {
            "output_text": json.dumps(
                {
                    "title": "Model Hosted Radio",
                    "summary": "A model-generated hosted radio draft.",
                    "blocks": [
                        {
                            "block_id": "block-0",
                            "title": "Opening Set",
                            "summary": "A hosted opening and one track.",
                            "position": 0,
                            "items": [
                                {
                                    "item_id": "item-0",
                                    "item_type": ProgramItemType.narration.value,
                                    "title": "Opening",
                                    "creator": None,
                                    "position": 0,
                                    "candidate_id": None,
                                    "playback_url": None,
                                    "duration_seconds": None,
                                    "narration_text": "Hi, I am Clownfish, your radio agent.",
                                    "explanation": None,
                                },
                                {
                                    "item_id": "item-1",
                                    "item_type": ContentType.music.value,
                                    "title": "Model Pick",
                                    "creator": "Model Artist",
                                    "position": 1,
                                    "candidate_id": "music-1",
                                    "playback_url": None,
                                    "duration_seconds": None,
                                    "narration_text": None,
                                    "explanation": "Chosen for the current context.",
                                },
                            ],
                        }
                    ],
                }
            )
        }


class FlatItemsOpenAIModelClient(OpenAIResponsesRadioModelClient):
    def __init__(self) -> None:
        super().__init__(api_key="test-key", model="test-model")

    def _post_json(self, path: str, body: dict[str, object]) -> dict[str, object]:
        del path, body
        return {
            "output_text": json.dumps(
                {
                    "title": "Flat Draft",
                    "summary": "A flat item list returned by the live model.",
                    "blocks": [
                        {
                            "type": "narration",
                            "text": "Good evening. We are keeping things soft tonight.",
                        },
                        {
                            "type": "track",
                            "candidate_id": "music-1",
                            "explanation": "A gentle opener for the current mood.",
                        },
                        {
                            "type": "narration",
                            "text": "Stay with the rain and let the room quiet down.",
                        },
                        {
                            "type": "track",
                            "candidate_id": "podcast-1",
                            "explanation": "A quiet spoken segment to keep the station hosted.",
                        },
                    ],
                }
            )
        }


class CapturingAnthropicModelClient(AnthropicRadioModelClient):
    def __init__(self) -> None:
        super().__init__(api_key="test-key", model="claude-test")
        self.path: str | None = None
        self.body: dict[str, object] | None = None

    def _post_json(
        self,
        path: str,
        body: dict[str, object],
        timeout: int,
    ) -> dict[str, object]:
        del timeout
        self.path = path
        self.body = body
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "title": "Anthropic Hosted Radio",
                            "summary": "An Anthropic-generated hosted radio draft.",
                            "blocks": [
                                {
                                    "block_id": "block-0",
                                    "title": "Opening Set",
                                    "summary": "A hosted opening and one track.",
                                    "position": 0,
                                    "items": [
                                        {
                                            "item_id": "item-0",
                                            "item_type": ProgramItemType.narration.value,
                                            "title": "Opening",
                                            "creator": None,
                                            "position": 0,
                                            "candidate_id": None,
                                            "playback_url": None,
                                            "duration_seconds": None,
                                            "narration_text": "Hi, I am Clownfish.",
                                            "explanation": None,
                                        },
                                        {
                                            "item_id": "item-1",
                                            "item_type": ContentType.music.value,
                                            "title": "Model Pick",
                                            "creator": "Model Artist",
                                            "position": 1,
                                            "candidate_id": "music-1",
                                            "playback_url": None,
                                            "duration_seconds": None,
                                            "narration_text": None,
                                            "explanation": "Chosen for the current context.",
                                        },
                                    ],
                                }
                            ],
                        }
                    ),
                }
            ]
        }


def make_raw_program(
    agent_input: RadioAgentInput,
    candidate_id: str,
    title: str = "Raw Song",
    playback_url: str = "mock://raw",
) -> dict[str, object]:
    return {
        "program_id": "runtime-test-program",
        "title": "Runtime Test Program",
        "summary": "A raw model response for runtime validation tests.",
        "context_snapshot": agent_input.context_snapshot.model_dump(mode="json"),
        "blocks": [
            {
                "block_id": "block-0",
                "title": "Opening",
                "position": 0,
                "items": [
                    {
                        "item_id": "item-0",
                        "item_type": ProgramItemType.narration.value,
                        "title": "Opening",
                        "position": 0,
                        "narration_text": "Start here.",
                    },
                    {
                        "item_id": "item-1",
                        "item_type": ContentType.music.value,
                        "title": title,
                        "position": 1,
                        "candidate_id": candidate_id,
                        "playback_url": playback_url,
                    },
                ],
            }
        ],
        "total_duration_minutes": agent_input.request.user_state.duration_minutes,
    }
