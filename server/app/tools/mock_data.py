import json
from pathlib import Path
from typing import Any

MOCK_DATA_ROOT = Path(__file__).resolve().parents[3] / "data" / "mock"


def read_mock_json(filename: str) -> dict[str, Any]:
    path = MOCK_DATA_ROOT / filename
    with path.open(encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError(f"mock data file {filename} must contain a JSON object")

    return data
