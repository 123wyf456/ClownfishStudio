from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import get_settings
from app.schemas import UserMusicMemory

SONG_REQUEST_PLAN_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "intent",
        "search_queries",
        "preferred_title",
        "preferred_artist",
        "preferred_tags",
        "mode",
        "reason",
    ],
    "properties": {
        "intent": {"type": "string"},
        "search_queries": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 6,
        },
        "preferred_title": {"type": ["string", "null"]},
        "preferred_artist": {"type": ["string", "null"]},
        "preferred_tags": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 8,
        },
        "mode": {"type": "string", "enum": ["precise_song", "artist_focus", "mood_mix", "general"]},
        "reason": {"type": "string"},
    },
}

SONG_REQUEST_SYSTEM_PROMPT = """
You are ClownfishStudio's song request planner.
Your job is to read a user's message and turn it into a compact music search plan.
Do not invent tracks that are not requested. Prefer extracting exact song title,
artist name, and short search queries. Return only JSON matching the schema.
""".strip()


@dataclass(frozen=True)
class SongRequestPlan:
    intent: str
    search_queries: list[str]
    preferred_title: str | None
    preferred_artist: str | None
    preferred_tags: list[str]
    mode: str
    reason: str


class SongRequestPlanner(Protocol):
    def plan(
        self,
        *,
        message: str,
        memory: UserMusicMemory,
        weather: dict[str, str | int | float | bool | None],
    ) -> SongRequestPlan:
        """Return a normalized song request plan."""


class MockSongRequestPlanner:
    def plan(
        self,
        *,
        message: str,
        memory: UserMusicMemory,
        weather: dict[str, str | int | float | bool | None],
    ) -> SongRequestPlan:
        del weather
        normalized_message = message.strip()
        explicit_query = _extract_explicit_query(normalized_message)
        ascii_tokens = _ascii_tokens(explicit_query or normalized_message)
        chinese_tokens = _chinese_tokens(explicit_query or normalized_message)
        preferred_title = _infer_preferred_title(explicit_query or normalized_message)
        preferred_artist = _infer_preferred_artist(explicit_query or normalized_message, memory)
        preferred_tags = _infer_preferred_tags(normalized_message, memory)

        queries = _unique_strings(
            [
                explicit_query,
                _join_query_parts(preferred_title, preferred_artist),
                _join_query_parts(preferred_title, preferred_tags[:2]),
                _join_query_parts(preferred_artist, preferred_tags[:2]),
                _join_query_parts(ascii_tokens[:3]),
                _join_query_parts(chinese_tokens[:2]),
            ]
        )

        mode = "general"
        if preferred_title:
            mode = "precise_song"
        elif preferred_artist:
            mode = "artist_focus"
        elif preferred_tags:
            mode = "mood_mix"

        return SongRequestPlan(
            intent=normalized_message or "play something fitting",
            search_queries=queries[:6] or ["late night radio"],
            preferred_title=preferred_title,
            preferred_artist=preferred_artist,
            preferred_tags=preferred_tags[:8],
            mode=mode,
            reason="Derived from explicit request terms and available taste memory.",
        )


class OpenAISongRequestPlanner:
    def __init__(self, *, api_key: str, model: str, base_url: str) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")

    def plan(
        self,
        *,
        message: str,
        memory: UserMusicMemory,
        weather: dict[str, str | int | float | bool | None],
    ) -> SongRequestPlan:
        body = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"{SONG_REQUEST_SYSTEM_PROMPT}\n"
                        "Return only one JSON object. Do not wrap it in Markdown."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "message": message,
                            "memory": memory.model_dump(mode="json"),
                            "weather": weather,
                            "schema": SONG_REQUEST_PLAN_SCHEMA,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
        }
        payload = self._post_json("/chat/completions", body)
        content = payload.get("choices", [{}])[0]
        message_payload = content.get("message") if isinstance(content, dict) else {}
        raw_content = (
            message_payload.get("content") if isinstance(message_payload, dict) else None
        )
        if not isinstance(raw_content, str):
            raise ValueError("song request planner returned no JSON content")
        loaded = json.loads(raw_content)
        if not isinstance(loaded, dict):
            raise ValueError("song request planner output must be a JSON object")
        return _normalize_plan(loaded, fallback_message=message)

    def _post_json(self, path: str, body: dict[str, object]) -> dict[str, object]:
        request = Request(
            f"{self._base_url}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=60) as response:
                raw_text = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ValueError(f"song request planner failed: {exc.code} {detail}") from exc
        except URLError as exc:
            raise ValueError(f"song request planner failed: {exc.reason}") from exc

        payload = json.loads(raw_text)
        if not isinstance(payload, dict):
            raise ValueError("song request planner response must be a JSON object")
        return payload


def build_song_request_planner() -> SongRequestPlanner:
    settings = get_settings()
    if settings.radio_agent_provider == "mock":
        return MockSongRequestPlanner()

    if settings.radio_agent_provider == "deepseek":
        if not settings.deepseek_api_key:
            return MockSongRequestPlanner()
        return OpenAISongRequestPlanner(
            api_key=settings.deepseek_api_key,
            model=settings.deepseek_model,
            base_url=settings.deepseek_base_url,
        )

    if not settings.openai_api_key:
        return MockSongRequestPlanner()
    return OpenAISongRequestPlanner(
        api_key=settings.openai_api_key,
        model=settings.radio_agent_model,
        base_url=settings.openai_base_url,
    )


def _normalize_plan(raw: dict[str, object], fallback_message: str) -> SongRequestPlan:
    queries = [
        value.strip()
        for value in raw.get("search_queries", [])
        if isinstance(value, str) and value.strip()
    ]
    preferred_tags = [
        value.strip()
        for value in raw.get("preferred_tags", [])
        if isinstance(value, str) and value.strip()
    ]
    mode = raw.get("mode")
    return SongRequestPlan(
        intent=_normalize_text(raw.get("intent")) or fallback_message.strip() or "play music",
        search_queries=(
            _unique_strings(queries)[:6]
            or [fallback_message.strip() or "late night radio"]
        ),
        preferred_title=_normalize_text(raw.get("preferred_title")),
        preferred_artist=_normalize_text(raw.get("preferred_artist")),
        preferred_tags=_unique_strings(preferred_tags)[:8],
        mode=mode if isinstance(mode, str) and mode else "general",
        reason=_normalize_text(raw.get("reason")) or "Generated from the user request.",
    )


def _extract_explicit_query(value: str) -> str | None:
    patterns = [
        r"(?:play|listen to|search for|find|recommend)\s+(.{2,48})",
        r"(?:\u60f3\u542c|\u64ad\u653e|\u641c\u7d22|\u627e\u4e00\u4e0b|\u5e2e\u6211\u627e|\u6765\u70b9|\u6765\u4e00\u70b9|\u63a8\u8350)(.{2,48})",
    ]
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match and match.group(1):
            return _clean_query(match.group(1))
    return _clean_query(value) if len(value) <= 32 else None


def _infer_preferred_title(value: str) -> str | None:
    cleaned = _clean_query(value)
    if not cleaned:
        return None
    by_match = re.search(r"(.+?)\s+by\s+(.+)", cleaned, flags=re.IGNORECASE)
    if by_match:
        return _normalize_text(by_match.group(1))
    chinese_match = re.search(r"(.+?)\s*[-/]\s*(.+)", cleaned)
    if chinese_match:
        return _normalize_text(chinese_match.group(1))
    if len(cleaned.split()) <= 5:
        return cleaned
    return None


def _infer_preferred_artist(value: str, memory: UserMusicMemory) -> str | None:
    cleaned = _clean_query(value)
    by_match = re.search(r"(.+?)\s+by\s+(.+)", cleaned, flags=re.IGNORECASE)
    if by_match:
        return _normalize_text(by_match.group(2))

    lower_cleaned = cleaned.lower()
    for artist in memory.favorite_artists:
        if artist.lower() in lower_cleaned:
            return artist
    return None


def _infer_preferred_tags(value: str, memory: UserMusicMemory) -> list[str]:
    tags: list[str] = []
    lower = value.lower()
    keyword_map = {
        "r&b": ("r&b", "soul"),
        "hip hop": ("hip hop", "rap"),
        "lofi": ("lofi", "focus"),
        "quiet": ("calm", "gentle"),
        "night": ("late night", "night radio"),
        "\u5b89\u9759": ("\u5b89\u9759", "\u8212\u7f13"),
        "\u96e8\u591c": ("\u96e8\u591c", "\u6df1\u591c"),
        "\u6df1\u591c": ("\u6df1\u591c", "\u591c\u665a"),
        "\u653e\u677e": ("\u653e\u677e", "\u8212\u7f13"),
    }
    for key, mapped_tags in keyword_map.items():
        if key in lower:
            tags.extend(mapped_tags)

    for genre in memory.favorite_genres[:4]:
        if genre.lower() in lower:
            tags.append(genre)

    return _unique_strings(tags)


def _ascii_tokens(value: str) -> list[str]:
    return _unique_strings(re.findall(r"[a-zA-Z0-9][a-zA-Z0-9'_-]+", value))


def _chinese_tokens(value: str) -> list[str]:
    return _unique_strings(re.findall(r"[\u4e00-\u9fff]{2,}", value))


def _clean_query(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = re.sub(
        r"[\u3001\u3002\uff0c\uff01\uff1f\uff1b\uff1a,.!?;:\"'`~()[\]{}<>]",
        " ",
        value,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def _join_query_parts(*groups: list[str] | tuple[str, ...] | str | None) -> str | None:
    parts: list[str] = []
    for group in groups:
        if group is None:
            continue
        if isinstance(group, str):
            if group.strip():
                parts.append(group.strip())
            continue
        for item in group:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
    joined = " ".join(_unique_strings(parts)).strip()
    return joined or None


def _unique_strings(values: list[str] | tuple[str, ...] | object) -> list[str]:
    unique_values: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        unique_values.append(normalized)
    return unique_values


def _normalize_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
