from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.main import app
from app.tools import get_program


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
    assert program["context_snapshot"]["weather"]["city"] == "Shanghai"
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
