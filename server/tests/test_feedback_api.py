from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.agents import DeterministicRadioModelClient, RadioAgentRuntime
from app.agents.song_request_agent import SongRequestPlan
from app.main import app
from app.services import program_generation
from app.tools import list_feedback_events, list_memory_update_hints


@pytest.fixture(autouse=True)
def fake_program_agents(monkeypatch) -> None:
    original_init = program_generation.ProgramGenerationService.__init__

    def init_with_fakes(self, runtime=None, song_request_planner=None):  # noqa: ANN001
        original_init(
            self,
            runtime=runtime
            or RadioAgentRuntime(model_client=DeterministicRadioModelClient()),
            song_request_planner=song_request_planner or _FeedbackSongPlanner(),
        )

    monkeypatch.setattr(
        program_generation.ProgramGenerationService,
        "__init__",
        init_with_fakes,
    )


def test_feedback_endpoint_saves_feedback_and_memory_hint() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/feedback",
        json={
            "feedback_type": "too_familiar",
            "user_id": "feedback-test-user",
            "program_id": "program-1",
            "item_id": "item-1",
            "candidate_id": "music-1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["feedback"]["feedback_type"] == "too_familiar"
    assert payload["memory_update_hint"]["action"] == "reduce_repetition"
    assert list_feedback_events(user_id="feedback-test-user")
    assert list_memory_update_hints(user_id="feedback-test-user")


def test_feedback_hint_affects_next_generated_program() -> None:
    client = TestClient(app)
    user_id = "feedback-flow-user"

    feedback_response = client.post(
        "/api/feedback",
        json={
            "feedback_type": "too_familiar",
            "user_id": user_id,
            "program_id": "program-old",
            "candidate_id": "music-1",
        },
    )
    generate_response = client.post("/api/programs/generate", json=make_generate_payload(user_id))

    assert feedback_response.status_code == 200
    assert generate_response.status_code == 200

    program = generate_response.json()["program"]
    selected_candidate_ids = {
        item["candidate_id"]
        for block in program["blocks"]
        for item in block["items"]
        if item["item_type"] != "narration"
    }
    assert "music-1" not in selected_candidate_ids


class _FeedbackSongPlanner:
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


def make_generate_payload(user_id: str) -> dict[str, object]:
    return {
        "user_id": user_id,
        "device_context": {
            "local_time": datetime(2026, 4, 30, 22, 30, tzinfo=UTC).isoformat(),
            "timezone": "Asia/Shanghai",
            "city_hint": "Shanghai",
        },
        "user_state": {
            "duration_minutes": 25,
            "free_text": "来一档轻松一点的电台。",
        },
        "max_candidates": 10,
    }
