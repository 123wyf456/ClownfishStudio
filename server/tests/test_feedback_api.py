from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.main import app
from app.tools import list_feedback_events, list_memory_update_hints


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
