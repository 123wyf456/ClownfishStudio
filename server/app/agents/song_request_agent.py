from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import get_settings
from app.schemas import ChatMessage, DeviceContext, UserMusicMemory, UserStateInput

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
Your job is to understand the user's message, current device context, weather,
listening state, recent history, and taste memory, then turn that into a compact
music search plan.
Do not invent tracks that are not requested. If the user explicitly asks for a
song or artist, extract that constraint and choose precise_song or artist_focus.
If the user describes a feeling, scene, weather, time, or need, infer search
queries and tags from that context instead of relying on fixed rules. Return only
JSON matching the schema.
search_queries must be short direct NetEase search terms such as song titles,
artist names, artist + genre, or genre names. Do not copy the user's full
sentence into search_queries. Do not include operational words like play,
recommend, listen, song, music, or Chinese request phrases. Do not include
weather placeholders such as unknown or weather unavailable.
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
        device_context: DeviceContext | None = None,
        user_state: UserStateInput | None = None,
        history: list[dict[str, str]] | None = None,
        chat_history: list[ChatMessage] | None = None,
    ) -> SongRequestPlan:
        """Return a normalized song request plan."""


class DeterministicSongRequestPlanner:
    def plan(
        self,
        *,
        message: str,
        memory: UserMusicMemory,
        weather: dict[str, str | int | float | bool | None],
        device_context: DeviceContext | None = None,
        user_state: UserStateInput | None = None,
        history: list[dict[str, str]] | None = None,
        chat_history: list[ChatMessage] | None = None,
    ) -> SongRequestPlan:
        del history
        normalized_message = _merge_recent_user_messages(message, chat_history or [])
        planning_message = "" if _is_auto_boot_message(normalized_message) else normalized_message
        context_tags = _context_terms(
            weather=weather,
            device_context=device_context,
            user_state=user_state,
        )
        explicit_query = _extract_explicit_query(planning_message)
        ascii_tokens = _ascii_tokens(explicit_query or planning_message)
        chinese_tokens = _chinese_tokens(explicit_query or planning_message)
        preferred_title = _infer_preferred_title(explicit_query or planning_message)
        preferred_artist = _infer_preferred_artist(explicit_query or planning_message, memory)
        user_preferred_tags = _infer_preferred_tags(planning_message, memory)
        preferred_tags = _unique_strings([*user_preferred_tags, *context_tags])
        queries = _unique_strings(
            sanitized_query
            for raw_query in [
                _join_query_parts(preferred_title, preferred_artist),
                preferred_artist,
                preferred_title,
                _join_query_parts(ascii_tokens[:2]),
                _join_query_parts(chinese_tokens[:2]),
                explicit_query,
                _join_query_parts(preferred_artist, user_preferred_tags[:1]),
                _join_query_parts(preferred_tags[:2]),
            ]
            if (sanitized_query := _sanitize_search_query(raw_query, normalized_message))
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
            search_queries=queries[:6]
            or _fallback_search_queries(
                planning_message,
                preferred_tags,
            ),
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
        device_context: DeviceContext | None = None,
        user_state: UserStateInput | None = None,
        history: list[dict[str, str]] | None = None,
        chat_history: list[ChatMessage] | None = None,
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
                            "device_context": (
                                device_context.model_dump(mode="json")
                                if device_context is not None
                                else None
                            ),
                            "user_state": (
                                user_state.model_dump(mode="json")
                                if user_state is not None
                                else None
                            ),
                            "memory": memory.model_dump(mode="json"),
                            "recent_history": history or [],
                            "recent_chat_history": [
                                message.model_dump(mode="json")
                                for message in (chat_history or [])[-8:]
                            ],
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
        raw_content = message_payload.get("content") if isinstance(message_payload, dict) else None
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
            with urlopen(request, timeout=8) as response:
                raw_text = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ValueError(f"song request planner failed: {exc.code} {detail}") from exc
        except TimeoutError as exc:
            raise ValueError("song request planner timed out") from exc
        except URLError as exc:
            raise ValueError(f"song request planner failed: {exc.reason}") from exc

        payload = json.loads(raw_text)
        if not isinstance(payload, dict):
            raise ValueError("song request planner response must be a JSON object")
        return payload


class AnthropicSongRequestPlanner:
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
        device_context: DeviceContext | None = None,
        user_state: UserStateInput | None = None,
        history: list[dict[str, str]] | None = None,
        chat_history: list[ChatMessage] | None = None,
    ) -> SongRequestPlan:
        body = {
            "model": self._model,
            "max_tokens": 1024,
            "system": (
                f"{SONG_REQUEST_SYSTEM_PROMPT}\n"
                "Return only one JSON object. Do not wrap it in Markdown."
            ),
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "message": message,
                            "device_context": (
                                device_context.model_dump(mode="json")
                                if device_context is not None
                                else None
                            ),
                            "user_state": (
                                user_state.model_dump(mode="json")
                                if user_state is not None
                                else None
                            ),
                            "memory": memory.model_dump(mode="json"),
                            "recent_history": history or [],
                            "recent_chat_history": [
                                message.model_dump(mode="json")
                                for message in (chat_history or [])[-8:]
                            ],
                            "weather": weather,
                            "schema": SONG_REQUEST_PLAN_SCHEMA,
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
        }
        payload = self._post_json("/v1/messages", body)
        raw_content = _extract_anthropic_text(payload)
        loaded = json.loads(raw_content)
        if not isinstance(loaded, dict):
            raise ValueError("song request planner output must be a JSON object")
        return _normalize_plan(loaded, fallback_message=message)

    def _post_json(self, path: str, body: dict[str, object]) -> dict[str, object]:
        request = Request(
            _join_base_url(self._base_url, path),
            data=json.dumps(body).encode("utf-8"),
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=8) as response:
                raw_text = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ValueError(f"song request planner failed: {exc.code} {detail}") from exc
        except TimeoutError as exc:
            raise ValueError("song request planner timed out") from exc
        except URLError as exc:
            raise ValueError(f"song request planner failed: {exc.reason}") from exc

        payload = json.loads(raw_text)
        if not isinstance(payload, dict):
            raise ValueError("song request planner response must be a JSON object")
        return payload


def build_song_request_planner() -> SongRequestPlanner:
    settings = get_settings()
    if settings.radio_agent_provider == "anthropic":
        if not settings.anthropic_api_key:
            raise ValueError("RADIO_AGENT_PROVIDER=anthropic requires ANTHROPIC_API_KEY")
        return AnthropicSongRequestPlanner(
            api_key=settings.anthropic_api_key,
            model=settings.radio_agent_model,
            base_url=settings.anthropic_base_url,
        )

    if not settings.openai_api_key:
        raise ValueError("RADIO_AGENT_PROVIDER=openai requires OPENAI_API_KEY")
    return OpenAISongRequestPlanner(
        api_key=settings.openai_api_key,
        model=settings.radio_agent_model,
        base_url=settings.openai_base_url,
    )


def _normalize_plan(raw: dict[str, object], fallback_message: str) -> SongRequestPlan:
    queries = _unique_strings(
        query
        for value in raw.get("search_queries", [])
        if isinstance(value, str)
        if (query := _sanitize_search_query(value, fallback_message))
    )
    preferred_tags = [
        value.strip()
        for value in raw.get("preferred_tags", [])
        if isinstance(value, str) and value.strip()
    ]
    mode = raw.get("mode")
    return SongRequestPlan(
        intent=_normalize_text(raw.get("intent")) or fallback_message.strip() or "play music",
        search_queries=queries[:6] or _fallback_search_queries(fallback_message),
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
    return None


def _infer_preferred_artist(value: str, memory: UserMusicMemory) -> str | None:
    cleaned = _clean_query(value)
    if not cleaned:
        return None
    by_match = re.search(r"(.+?)\s+by\s+(.+)", cleaned, flags=re.IGNORECASE)
    if by_match:
        return _normalize_text(by_match.group(2))

    artist_request_matches = re.findall(
        r"([A-Za-z0-9 .'\-&\u4e00-\u9fff]{2,32})\s*的歌",
        cleaned,
    )
    for candidate in reversed(artist_request_matches):
        normalized_candidate = re.sub(
            r"^(推荐|想听|播放|放一些|放点|来点|帮我找|搜一下|找一下)\s*",
            "",
            candidate.strip(),
        )
        normalized_candidate = _sanitize_search_query(normalized_candidate, value)
        if normalized_candidate and normalized_candidate not in {"轻松", "安静", "放松"}:
            return normalized_candidate

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


def _context_terms(
    *,
    weather: dict[str, str | int | float | bool | None],
    device_context: DeviceContext | None,
    user_state: UserStateInput | None,
) -> list[str]:
    terms: list[str] = []
    if user_state is not None:
        if user_state.mood is not None:
            terms.append(user_state.mood.value)
        terms.extend(need.value for need in user_state.needs)

    condition = weather.get("condition")
    if isinstance(condition, str) and condition.strip():
        terms.append(condition.strip().lower())

    if device_context is not None:
        hour = device_context.local_time.hour
        if 22 <= hour or hour < 5:
            terms.extend(["late night", "\u6df1\u591c"])
        elif 5 <= hour < 12:
            terms.append("morning")
        elif 18 <= hour < 23:
            terms.append("evening")

    return _unique_strings(terms)


def _merge_recent_user_messages(message: str, chat_history: list[ChatMessage]) -> str:
    messages = [
        item.text.strip() for item in chat_history[-6:] if item.role == "user" and item.text.strip()
    ]
    if message.strip() and (not messages or messages[-1] != message.strip()):
        messages.append(message.strip())
    return " ".join(messages[-3:]).strip()


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


def _sanitize_search_query(value: str | None, user_message: str = "") -> str | None:
    cleaned = _clean_query(value)
    if not cleaned:
        return None

    normalized_user_message = _clean_query(user_message)
    if (
        normalized_user_message
        and cleaned.lower() == normalized_user_message.lower()
        and _looks_like_request_sentence(cleaned)
    ):
        return None

    cleaned = re.sub(
        r"\b(play|listen to|search for|find|recommend|songs?|music|tracks?)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"(我想听|想听|播放|推荐|放一些|放点|来点|来一些|帮我找|搜一下|找一下|"
        r"歌曲|歌单|音乐|的歌)",
        " ",
        cleaned,
    )
    cleaned = re.sub(
        r"\b(companionship|unknown|weather unavailable|unavailable)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\b(clownfishstudio|clownfish)\b|启动|打招呼|自我介绍|此刻的电台|电台",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) < 2:
        return None
    return cleaned


def _looks_like_request_sentence(value: str) -> bool:
    return bool(
        re.search(
            r"\b(play|listen|search|find|recommend|songs?|music|tracks?)\b|"
            r"(我想听|想听|播放|推荐|放一些|放点|来点|来一些|帮我找|搜一下|找一下|"
            r"歌曲|歌单|音乐|的歌)",
            value,
            flags=re.IGNORECASE,
        )
    )


def _is_auto_boot_message(value: str) -> bool:
    text = value.strip().lower()
    if not text:
        return False
    markers = [
        "open clownfishstudio",
        "create a fresh hosted radio set",
        "start a small personal radio set",
        "generate a fresh station",
        "启动 clownfishstudio",
        "启动clownfishstudio",
        "此刻的电台",
    ]
    return any(marker in text for marker in markers)


def _fallback_search_queries(message: str, preferred_tags: list[str] | None = None) -> list[str]:
    cleaned = _clean_query(message) or ""
    artist = _infer_preferred_artist(cleaned, UserMusicMemory(user_id="fallback"))
    title = _infer_preferred_title(cleaned)
    tags = preferred_tags or _infer_preferred_tags(
        cleaned,
        UserMusicMemory(user_id="fallback"),
    )
    tokens = [*_ascii_tokens(cleaned)[:2], *_chinese_tokens(cleaned)[:2]]

    return _unique_strings(
        query
        for value in [
            _join_query_parts(title, artist),
            artist,
            title,
            _join_query_parts(tags[:2]),
            _join_query_parts(tokens[:2]),
        ]
        if (query := _sanitize_search_query(value, message))
    )[:3]


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


def _extract_anthropic_text(payload: dict[str, object]) -> str:
    content = payload.get("content")
    if not isinstance(content, list):
        raise ValueError("song request planner returned no JSON content")

    chunks: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str):
            chunks.append(text)

    raw_content = "".join(chunks).strip()
    if not raw_content:
        raise ValueError("song request planner returned no JSON content")
    return raw_content


def _join_base_url(base_url: str, path: str) -> str:
    normalized_base = base_url.rstrip("/")
    if normalized_base.endswith("/v1") and path.startswith("/v1/"):
        return f"{normalized_base}{path.removeprefix('/v1')}"
    return f"{normalized_base}{path}"
