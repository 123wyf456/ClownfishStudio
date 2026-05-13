from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas import (
    CandidateItem,
    ContentType,
    ContextSnapshot,
    DeviceContext,
    FeedbackEvent,
    FeedbackType,
    GenerateProgramRequest,
    GenerateProgramResponse,
    ListeningNeed,
    Mood,
    ProgramBlock,
    ProgramItem,
    ProgramItemType,
    RadioProgram,
    UserStateInput,
)


def make_device_context() -> DeviceContext:
    return DeviceContext(
        local_time=datetime(2026, 4, 30, 22, 30, tzinfo=UTC),
        timezone="Asia/Shanghai",
        locale="zh-CN",
        city_hint="Shanghai",
        latitude=31.2304,
        longitude=121.4737,
    )


def make_user_state() -> UserStateInput:
    return UserStateInput(
        mood=Mood.tired,
        energy_level=2,
        needs=[ListeningNeed.relax],
        duration_minutes=25,
        free_text="今天有点累，想听轻松一点的内容。",
    )


def test_generate_program_request_accepts_mobile_context() -> None:
    request = GenerateProgramRequest(
        user_id="user-1",
        device_context=make_device_context(),
        user_state=make_user_state(),
    )

    assert request.user_id == "user-1"
    assert request.max_candidates == 20
    assert request.device_context.city_hint == "Shanghai"


def test_device_context_rejects_invalid_coordinates() -> None:
    with pytest.raises(ValidationError):
        DeviceContext(
            local_time=datetime(2026, 4, 30, 22, 30, tzinfo=UTC),
            timezone="Asia/Shanghai",
            latitude=120,
        )


def test_user_state_rejects_too_short_program_duration() -> None:
    with pytest.raises(ValidationError):
        UserStateInput(duration_minutes=3)


def test_candidate_item_serializes_enum_values_for_json() -> None:
    candidate = CandidateItem(
        candidate_id="music-1",
        content_type=ContentType.music,
        title="Mock Song",
        creator="Mock Artist",
        duration_seconds=180,
        playback_url="mock://music-1",
        tags=["warm", "night"],
        source="mock",
    )

    assert candidate.model_dump(mode="json")["content_type"] == "music"


def test_program_item_requires_candidate_id_for_playable_content() -> None:
    with pytest.raises(ValidationError, match="candidate_id"):
        ProgramItem(
            item_id="item-1",
            item_type=ProgramItemType.music,
            title="Song without candidate",
            position=0,
        )


def test_program_item_requires_text_for_narration() -> None:
    with pytest.raises(ValidationError, match="narration_text"):
        ProgramItem(
            item_id="item-1",
            item_type=ProgramItemType.narration,
            title="Opening",
            position=0,
        )


def test_radio_program_response_contract() -> None:
    context_snapshot = ContextSnapshot(
        device_context=make_device_context(),
        user_state=make_user_state(),
        weather={"condition": "cloudy", "temperature_celsius": 19.5},
    )
    program = RadioProgram(
        program_id="program-1",
        title="夜晚恢复电台",
        summary="一档帮助用户慢慢放松下来的个人电台。",
        context_snapshot=context_snapshot,
        total_duration_minutes=25,
        blocks=[
            ProgramBlock(
                block_id="block-1",
                title="开场和第一首歌",
                position=0,
                items=[
                    ProgramItem(
                        item_id="item-1",
                        item_type=ProgramItemType.narration,
                        title="开场",
                        position=0,
                        narration_text="先把节奏放慢一点。",
                    ),
                    ProgramItem(
                        item_id="item-2",
                        item_type=ProgramItemType.music,
                        title="Mock Song",
                        position=1,
                        candidate_id="music-1",
                        playback_url="mock://music-1",
                    ),
                ],
            )
        ],
    )
    response = GenerateProgramResponse(
        request_id="request-1",
        program=program,
        candidate_count=1,
    )

    payload = response.model_dump(mode="json")
    assert payload["program"]["blocks"][0]["items"][1]["candidate_id"] == "music-1"
    assert payload["program"]["context_snapshot"]["weather"]["condition"] == "cloudy"


def test_feedback_event_accepts_defined_feedback_types() -> None:
    feedback = FeedbackEvent(
        user_id="user-1",
        program_id="program-1",
        item_id="item-2",
        candidate_id="music-1",
        feedback_type=FeedbackType.want_more_like_this,
    )

    assert feedback.feedback_type is FeedbackType.want_more_like_this
