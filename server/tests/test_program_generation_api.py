from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.agents import DeterministicRadioModelClient, RadioAgentRuntime
from app.agents.song_request_agent import SongRequestPlan
from app.main import app
from app.services import program_generation
from app.tools import get_program


@pytest.fixture(autouse=True)
def fake_program_agents(monkeypatch) -> None:
    original_init = program_generation.ProgramGenerationService.__init__

    def init_with_fakes(self, runtime=None, song_request_planner=None):  # noqa: ANN001
        original_init(
            self,
            runtime=runtime
            or RadioAgentRuntime(model_client=DeterministicRadioModelClient()),
            song_request_planner=song_request_planner or _ProgramApiSongPlanner(),
        )

    monkeypatch.setattr(
        program_generation.ProgramGenerationService,
        "__init__",
        init_with_fakes,
    )


def test_generate_program_endpoint_returns_radio_program() -> None:
    client = TestClient(app)

    response = client.post("/api/programs/generate", json=make_generate_payload())

    assert response.status_code == 200
    payload = response.json()
    program = payload["program"]
    playable_items = [
        item
        for block in program["blocks"]
        for item in block["items"]
        if item["item_type"] != "narration"
    ]

    assert payload["request_id"].startswith("request-")
    assert payload["candidate_count"] > 0
    assert program["context_snapshot"]["weather"]["source"] == "disabled"
    assert playable_items
    assert all(item["candidate_id"] for item in playable_items)
    assert get_program(program["program_id"]) is not None


def test_generate_program_endpoint_validates_request_body() -> None:
    client = TestClient(app)
    payload = make_generate_payload()
    payload["user_state"]["duration_minutes"] = 3

    response = client.post("/api/programs/generate", json=payload)

    assert response.status_code == 422


def make_generate_payload() -> dict[str, object]:
    return {
        "user_id": "demo-user",
        "device_context": {
            "local_time": datetime(2026, 4, 30, 22, 30, tzinfo=UTC).isoformat(),
            "timezone": "Asia/Shanghai",
            "locale": "zh-CN",
            "city_hint": "Shanghai",
            "latitude": 31.2304,
            "longitude": 121.4737,
        },
        "user_state": {
            "mood": "tired",
            "energy_level": 2,
            "needs": ["relax"],
            "duration_minutes": 25,
            "free_text": "今天有点累，想听一档恢复精力的电台。",
        },
        "max_candidates": 10,
    }


class _ProgramApiSongPlanner:
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
