import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.agents.prompts import SYSTEM_PROMPT
from app.schemas import (
    CandidateItem,
    ChatMessage,
    ChatMusicConstraints,
    ChatRouterResult,
    ContentType,
    ContextSnapshot,
    GenerateProgramRequest,
    ProgramItemType,
    UserMusicMemory,
)

RADIO_PROGRAM_DRAFT_JSON_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "summary", "blocks"],
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "blocks": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["block_id", "title", "summary", "position", "items"],
                "properties": {
                    "block_id": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": ["string", "null"]},
                    "position": {"type": "integer"},
                    "items": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "item_id",
                                "item_type",
                                "title",
                                "creator",
                                "position",
                                "candidate_id",
                                "playback_url",
                                "duration_seconds",
                                "narration_text",
                                "explanation",
                            ],
                            "properties": {
                                "item_id": {"type": "string"},
                                "item_type": {
                                    "type": "string",
                                    "enum": ["narration", "music", "podcast"],
                                },
                                "title": {"type": "string"},
                                "creator": {"type": ["string", "null"]},
                                "position": {"type": "integer"},
                                "candidate_id": {"type": ["string", "null"]},
                                "playback_url": {"type": ["string", "null"]},
                                "duration_seconds": {"type": ["integer", "null"]},
                                "narration_text": {"type": ["string", "null"]},
                                "explanation": {"type": ["string", "null"]},
                            },
                        },
                    },
                },
            },
        },
    },
}
PROGRAM_AGENT_TIMEOUT_SECONDS = 60
SHORT_TEXT_AGENT_TIMEOUT_SECONDS = 8


@dataclass(frozen=True)
class RadioAgentInput:
    request: GenerateProgramRequest
    context_snapshot: ContextSnapshot
    memory: UserMusicMemory
    history: list[dict[str, str]]
    candidate_items: list[CandidateItem]
    chat_history: list[ChatMessage]
    prompt: str


class RadioModelClient(Protocol):
    def generate_program(self, agent_input: RadioAgentInput) -> dict[str, object]:
        """Return a raw RadioProgram-compatible payload."""

    def generate_short_text(self, prompt: str) -> str:
        """Return a short host text payload."""

    def plan_chat_turn(self, prompt: str) -> ChatRouterResult:
        """Return structured router signals for the listener's latest message."""


class ModelRequestError(ValueError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class DeterministicRadioModelClient:
    """Deterministic test double for program generation.

    Production runtime does not select this client automatically.
    """

    def generate_program(self, agent_input: RadioAgentInput) -> dict[str, object]:
        selected_candidates = self._select_candidates(agent_input)
        items = self._build_program_items(agent_input, selected_candidates)

        return {
            "program_id": f"program-{uuid4().hex}",
            "title": self._build_program_title(agent_input),
            "summary": self._build_program_summary(agent_input, selected_candidates),
            "context_snapshot": agent_input.context_snapshot.model_dump(mode="json"),
            "blocks": [
                {
                    "block_id": "block-0",
                    "title": self._build_block_title(agent_input),
                    "summary": self._build_block_summary(agent_input, selected_candidates),
                    "position": 0,
                    "items": items,
                }
            ],
            "total_duration_minutes": agent_input.request.user_state.duration_minutes,
            "generated_at": datetime.now(UTC).isoformat(),
        }

    def generate_short_text(self, prompt: str) -> str:
        del prompt
        raise ModelRequestError(
            "A real LLM provider is required to answer chat turns."
        )

    def plan_chat_turn(self, prompt: str) -> ChatRouterResult:
        del prompt
        raise ModelRequestError(
            "A real LLM provider is required to understand chat turns."
        )

    def _build_program_items(
        self,
        agent_input: RadioAgentInput,
        selected_candidates: list[CandidateItem],
    ) -> list[dict[str, object]]:
        items: list[dict[str, object]] = [
            {
                "item_id": "item-0",
                "item_type": ProgramItemType.narration.value,
                "title": "Opening",
                "position": 0,
                "narration_text": self._build_intro(agent_input, selected_candidates),
            }
        ]

        position = 1
        previous_candidate: CandidateItem | None = None
        for candidate in selected_candidates:
            if previous_candidate is not None:
                items.append(
                    {
                        "item_id": f"item-{position}",
                        "item_type": ProgramItemType.narration.value,
                        "title": f"Bridge to {candidate.title}",
                        "position": position,
                        "narration_text": self._build_bridge(
                            agent_input=agent_input,
                            previous_candidate=previous_candidate,
                            next_candidate=candidate,
                        ),
                    }
                )
                position += 1

            items.append(
                {
                    "item_id": f"item-{position}",
                    "item_type": candidate.content_type.value,
                    "title": candidate.title,
                    "creator": candidate.creator,
                    "position": position,
                    "candidate_id": candidate.candidate_id,
                    "playback_url": candidate.playback_url,
                    "duration_seconds": candidate.duration_seconds,
                    "explanation": self._build_track_explanation(
                        agent_input=agent_input,
                        candidate=candidate,
                    ),
                }
            )
            position += 1
            previous_candidate = candidate

        return items

    def _select_candidates(self, agent_input: RadioAgentInput) -> list[CandidateItem]:
        target_count = self._target_track_count(agent_input)
        recent_candidate_ids = {
            event["candidate_id"] for event in agent_input.history if event.get("candidate_id")
        } | set(agent_input.memory.recent_candidate_ids)
        scored_candidates = [
            (
                self._score_candidate(agent_input, candidate),
                _candidate_rotation_key(agent_input, candidate),
                index,
                candidate,
            )
            for index, candidate in enumerate(agent_input.candidate_items)
        ]
        scored_candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
        fresh_scored_candidates = [
            item for item in scored_candidates if item[3].candidate_id not in recent_candidate_ids
        ]
        selectable_candidates = fresh_scored_candidates or scored_candidates
        return [candidate for _, _, _, candidate in selectable_candidates[:target_count]]

    def _target_track_count(self, agent_input: RadioAgentInput) -> int:
        duration = agent_input.request.user_state.duration_minutes
        available = len(agent_input.candidate_items)
        if duration <= 25:
            preferred = 7
        elif duration <= 40:
            preferred = 8
        else:
            preferred = 9
        return max(1, min(preferred, available))

    def _score_candidate(
        self,
        agent_input: RadioAgentInput,
        candidate: CandidateItem,
    ) -> int:
        user_state = agent_input.request.user_state
        recent_candidate_ids = {
            event["candidate_id"] for event in agent_input.history if event.get("candidate_id")
        } | set(agent_input.memory.recent_candidate_ids)
        requested_tags = {
            *(need.value.lower() for need in user_state.needs),
            *((user_state.mood.value.lower(),) if user_state.mood is not None else ()),
        }
        candidate_tags = {tag.lower() for tag in candidate.tags}
        query_tokens = _tokenize(user_state.free_text)
        search_text = " ".join([candidate.title, candidate.creator, *candidate.tags]).lower()
        creator_fragments = {
            fragment.strip().lower()
            for fragment in re.split(r"[,&/]|feat\\.|Feat\\.|FEAT\\.", candidate.creator)
            if fragment.strip()
        }
        recent_creators = {
            fragment.strip().lower()
            for event in agent_input.history
            for fragment in re.split(
                r"[,&/]|feat\\.|Feat\\.|FEAT\\.",
                event.get("creator", ""),
            )
            if fragment.strip()
        }
        favorite_artists = {artist.lower() for artist in agent_input.memory.favorite_artists}
        disliked_artists = {artist.lower() for artist in agent_input.memory.disliked_artists}

        score = 0
        if candidate.content_type is ContentType.music:
            score += 3
        if candidate.playback_url:
            score += 2
        if candidate.candidate_id in recent_candidate_ids:
            score -= 9
        if creator_fragments.intersection(recent_creators):
            score -= 4
        score += 4 * len(candidate_tags.intersection(requested_tags))
        score += 2 * sum(1 for token in query_tokens if token in search_text)
        score += 3 * len(
            candidate_tags.intersection(
                genre.lower() for genre in agent_input.memory.favorite_genres
            )
        )
        if creator_fragments.intersection(favorite_artists):
            score += 4
        if creator_fragments.intersection(disliked_artists):
            score -= 10
        if "user_preference" in candidate_tags:
            score += 6
        if "recent_favorite" in candidate_tags:
            score += 4
        if "liked_track" in candidate_tags:
            score += 3
        if "playlist_seed" in candidate_tags:
            score += 2
        if "personalized_recommendation" in candidate_tags:
            score += 4
        if "favorite_artist_match" in candidate_tags:
            score += 3
        if "favorite_genre_match" in candidate_tags:
            score += 2
        if "query_match" in candidate_tags:
            score += 2
        if candidate.source == "netease_cloud_music":
            score += 1

        return score

    def _build_intro(
        self,
        agent_input: RadioAgentInput,
        selected_candidates: list[CandidateItem],
    ) -> str:
        del selected_candidates
        if _prefers_chinese(_language_hint(agent_input)):
            return "你好，我是 Clownfish。先陪你播一小段。"
        return "Hi, I'm Clownfish. I'll keep you company for a short set."

    def _build_bridge(
        self,
        agent_input: RadioAgentInput,
        previous_candidate: CandidateItem,
        next_candidate: CandidateItem,
    ) -> str:
        atmosphere = _atmosphere_text(agent_input, [previous_candidate, next_candidate])
        if _prefers_chinese(_language_hint(agent_input)):
            return f"下一首换成 {next_candidate.title}，继续保持{atmosphere}。"
        return f"Next is {next_candidate.title}; I will keep the station {atmosphere}."

    def _build_track_explanation(
        self,
        agent_input: RadioAgentInput,
        candidate: CandidateItem,
    ) -> str:
        station_focus = _station_focus(agent_input)
        tag_text = _tag_text(candidate)
        return (
            f"{candidate.title} by {candidate.creator} fits {station_focus}. "
            f"I placed it here because its available tags point toward {tag_text}."
        )

    def _build_program_title(self, agent_input: RadioAgentInput) -> str:
        city = _city(agent_input)
        period = _day_period(_local_datetime(agent_input))
        return f"Clownfish {period} Radio - {city}"

    def _build_program_summary(
        self,
        agent_input: RadioAgentInput,
        selected_candidates: list[CandidateItem],
    ) -> str:
        return (
            f"A {len(selected_candidates)}-track agent-built station for "
            f"{_city(agent_input)} on {_format_local_date(agent_input)}, shaped by "
            f"{_weather_text(agent_input)}, the user's current state, recent history, "
            "and playable candidates returned by tools."
        )

    def _build_block_title(self, agent_input: RadioAgentInput) -> str:
        return f"{_day_period(_local_datetime(agent_input))} opening set"

    def _build_block_summary(
        self,
        agent_input: RadioAgentInput,
        selected_candidates: list[CandidateItem],
    ) -> str:
        return (
            f"Opening narration plus {_track_list(selected_candidates)}. "
            f"The sequence aims for {_atmosphere_text(agent_input, selected_candidates)}."
        )


class OpenAIResponsesRadioModelClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        prefer_chat_completions: bool = False,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._prefer_chat_completions = prefer_chat_completions

    def generate_program(self, agent_input: RadioAgentInput) -> dict[str, object]:
        if self._prefer_chat_completions:
            payload = self._post_json_with_timeout(
                "/chat/completions",
                self._build_chat_completions_body(agent_input),
                timeout=PROGRAM_AGENT_TIMEOUT_SECONDS,
            )
        else:
            try:
                payload = self._post_json_with_timeout(
                    "/responses",
                    self._build_responses_body(agent_input),
                    timeout=PROGRAM_AGENT_TIMEOUT_SECONDS,
                )
            except ModelRequestError as exc:
                if not _should_try_chat_completions_fallback(exc):
                    raise
                payload = self._post_json_with_timeout(
                    "/chat/completions",
                    self._build_chat_completions_body(agent_input),
                    timeout=PROGRAM_AGENT_TIMEOUT_SECONDS,
                )

        draft = _load_response_json(payload)
        return _complete_program_payload(draft=draft, agent_input=agent_input)

    def generate_short_text(self, prompt: str) -> str:
        body = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": 'Return only one JSON object shaped as {"text":"..."}.',
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        payload = self._post_json_with_timeout(
            "/chat/completions",
            body,
            timeout=SHORT_TEXT_AGENT_TIMEOUT_SECONDS,
        )
        raw_text = _extract_response_text(payload)
        try:
            loaded = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError("short text agent returned non-JSON output") from exc
        if not isinstance(loaded, dict):
            raise ValueError("short text agent output must be a JSON object")
        text = loaded.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("short text agent output missing text")
        return _shorten_text(text)

    def plan_chat_turn(self, prompt: str) -> ChatRouterResult:
        body = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return only one JSON object with emotion, need_chat, "
                        "need_music, need_info, need_control, control_action, "
                        "music_constraints, and confidence. Do not write a reply."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        payload = self._post_json_with_timeout(
            "/chat/completions",
            body,
            timeout=SHORT_TEXT_AGENT_TIMEOUT_SECONDS,
        )
        raw_text = _extract_response_text(payload)
        return _load_chat_router_result(raw_text)

    def _post_json_with_timeout(
        self,
        path: str,
        body: dict[str, object],
        timeout: int,
    ) -> dict[str, object]:
        try:
            return self._post_json(path, body, timeout=timeout)
        except TypeError as exc:
            if "timeout" not in str(exc):
                raise
            return self._post_json(path, body)

    def _build_responses_body(self, agent_input: RadioAgentInput) -> dict[str, object]:
        return {
            "model": self._model,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "radio_program_draft",
                    "description": (
                        "A hosted radio program draft. Server-owned fields such as "
                        "program_id, context_snapshot, total duration, and generated_at "
                        "are added after model generation."
                    ),
                    "strict": True,
                    "schema": RADIO_PROGRAM_DRAFT_JSON_SCHEMA,
                }
            },
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                f"{SYSTEM_PROMPT}\n"
                                "Return only the structured JSON draft requested by "
                                "the response schema."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": agent_input.prompt}],
                },
            ],
        }

    def _build_chat_completions_body(self, agent_input: RadioAgentInput) -> dict[str, object]:
        return {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"{SYSTEM_PROMPT}\n"
                        "Return only one JSON object. Do not wrap it in Markdown. "
                        "The object must contain title, summary, and blocks."
                    ),
                },
                {"role": "user", "content": agent_input.prompt},
            ],
            "response_format": {"type": "json_object"},
        }

    def _post_json(
        self,
        path: str,
        body: dict[str, object],
        timeout: int = 55,
    ) -> dict[str, object]:
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
            with urlopen(request, timeout=timeout) as response:
                raw_text = response.read().decode("utf-8", errors="replace")
                try:
                    payload = json.loads(raw_text)
                except json.JSONDecodeError as exc:
                    raise ModelRequestError(
                        f"LLM agent response was not JSON: {_safe_snippet(raw_text)}"
                    ) from exc
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ModelRequestError(
                f"LLM agent request failed: {exc.code} {_safe_snippet(detail)}",
                status_code=exc.code,
            ) from exc
        except TimeoutError as exc:
            raise ModelRequestError("LLM agent request timed out") from exc
        except URLError as exc:
            raise ModelRequestError(f"LLM agent request failed: {exc.reason}") from exc

        if not isinstance(payload, dict):
            raise ModelRequestError("LLM agent response must be a JSON object")

        return payload


class AnthropicRadioModelClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.anthropic.com",
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")

    def generate_program(self, agent_input: RadioAgentInput) -> dict[str, object]:
        body = {
            "model": self._model,
            "max_tokens": 4096,
            "system": (
                f"{SYSTEM_PROMPT}\n"
                "Return only one JSON object. Do not wrap it in Markdown. "
                "The object must contain title, summary, and blocks."
            ),
            "messages": [{"role": "user", "content": agent_input.prompt}],
        }
        payload = self._post_json(
            "/v1/messages",
            body,
            timeout=PROGRAM_AGENT_TIMEOUT_SECONDS,
        )
        draft = _load_response_json(payload)
        return _complete_program_payload(draft=draft, agent_input=agent_input)

    def generate_short_text(self, prompt: str) -> str:
        body = {
            "model": self._model,
            "max_tokens": 512,
            "system": 'Return only one JSON object shaped as {"text":"..."}.',
            "messages": [{"role": "user", "content": prompt}],
        }
        payload = self._post_json(
            "/v1/messages",
            body,
            timeout=SHORT_TEXT_AGENT_TIMEOUT_SECONDS,
        )
        raw_text = _extract_response_text(payload)
        try:
            loaded = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError("short text agent returned non-JSON output") from exc
        if not isinstance(loaded, dict):
            raise ValueError("short text agent output must be a JSON object")
        text = loaded.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("short text agent output missing text")
        return _shorten_text(text)

    def plan_chat_turn(self, prompt: str) -> ChatRouterResult:
        body = {
            "model": self._model,
            "max_tokens": 512,
            "system": (
                "Return only one JSON object with emotion, need_chat, need_music, "
                "need_info, need_control, control_action, music_constraints, and "
                "confidence. Do not write a reply."
            ),
            "messages": [{"role": "user", "content": prompt}],
        }
        payload = self._post_json(
            "/v1/messages",
            body,
            timeout=SHORT_TEXT_AGENT_TIMEOUT_SECONDS,
        )
        raw_text = _extract_response_text(payload)
        return _load_chat_router_result(raw_text)

    def _post_json(
        self,
        path: str,
        body: dict[str, object],
        timeout: int,
    ) -> dict[str, object]:
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
            with urlopen(request, timeout=timeout) as response:
                raw_text = response.read().decode("utf-8", errors="replace")
                try:
                    payload = json.loads(raw_text)
                except json.JSONDecodeError as exc:
                    raise ModelRequestError(
                        f"Anthropic agent response was not JSON: {_safe_snippet(raw_text)}"
                    ) from exc
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ModelRequestError(
                f"Anthropic agent request failed: {exc.code} {_safe_snippet(detail)}",
                status_code=exc.code,
            ) from exc
        except TimeoutError as exc:
            raise ModelRequestError("Anthropic agent request timed out") from exc
        except URLError as exc:
            raise ModelRequestError(f"Anthropic agent request failed: {exc.reason}") from exc

        if not isinstance(payload, dict):
            raise ModelRequestError("Anthropic agent response must be a JSON object")

        return payload


def _should_try_chat_completions_fallback(exc: ModelRequestError) -> bool:
    if exc.status_code in {401, 403}:
        return False
    return True


CONTROL_ACTIONS = {"play", "pause", "next", "previous", "skip", "stop", "like", "favorite"}


def _load_response_json(payload: dict[str, object]) -> dict[str, object]:
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        raise ValueError(
            f"LLM agent request failed: {message if isinstance(message, str) else error}"
        )

    text = _extract_response_text(payload)

    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM agent returned non-JSON output") from exc

    if not isinstance(loaded, dict):
        raise ValueError("LLM agent output must be a JSON object")

    return loaded


def _load_chat_router_result(raw_text: str) -> ChatRouterResult:
    try:
        loaded = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError("chat router returned non-JSON output") from exc
    if not isinstance(loaded, dict):
        raise ValueError("chat router output must be a JSON object")

    normalized = _normalize_chat_router_payload(loaded)
    try:
        return ChatRouterResult.model_validate(normalized)
    except ValueError as exc:
        raise ValueError("chat router output failed validation") from exc


def _normalize_chat_router_payload(payload: dict[str, object]) -> dict[str, object]:
    if "intent" in payload:
        return _legacy_intent_to_router_payload(payload)

    constraints = payload.get("music_constraints")
    if not isinstance(constraints, dict):
        constraints = {}

    return {
        "emotion": _normalize_text(payload.get("emotion")),
        "need_chat": _normalize_bool(payload.get("need_chat")),
        "need_music": _normalize_bool(payload.get("need_music")),
        "need_info": _normalize_bool(payload.get("need_info")),
        "need_control": _normalize_bool(payload.get("need_control")),
        "control_action": _normalize_control_action(payload.get("control_action")),
        "music_constraints": _normalize_music_constraints(constraints),
        "confidence": _normalize_confidence(payload.get("confidence")),
    }


def _legacy_intent_to_router_payload(payload: dict[str, object]) -> dict[str, object]:
    intent = _normalize_text(payload.get("intent")) or "chat_only"
    message = _normalize_text(payload.get("reply_text")) or _normalize_text(payload.get("text"))
    if intent == "song_request":
        return (
            _fallback_chat_router_result(message or "")
            .model_copy(update={"need_music": True, "need_chat": True})
            .model_dump(mode="json")
        )
    if intent == "retune_program":
        return (
            _fallback_chat_router_result(message or "")
            .model_copy(update={"need_music": True, "need_chat": True})
            .model_dump(mode="json")
        )
    if intent == "config_help":
        return ChatRouterResult(
            emotion="neutral",
            need_chat=True,
            confidence=0.6,
        ).model_dump(mode="json")
    return ChatRouterResult(
        emotion="neutral",
        need_chat=True,
        confidence=0.5,
    ).model_dump(mode="json")


def _normalize_music_constraints(payload: dict[object, object]) -> dict[str, object]:
    return {
        "artists": _normalize_string_list(payload.get("artists") or payload.get("artist")),
        "tracks": _normalize_string_list(payload.get("tracks") or payload.get("track")),
        "genres": _normalize_string_list(payload.get("genres") or payload.get("genre")),
        "languages": _normalize_string_list(payload.get("languages") or payload.get("language")),
        "scenes": _normalize_string_list(payload.get("scenes") or payload.get("scene")),
        "mood": _normalize_text(payload.get("mood")),
        "energy": _normalize_text(payload.get("energy")),
        "avoid": _normalize_string_list(payload.get("avoid")),
        "raw_query": _normalize_text(payload.get("raw_query") or payload.get("query")),
    }


def _normalize_string_list(value: object) -> list[str]:
    if isinstance(value, str):
        normalized = value.strip()
        return [normalized] if normalized else []
    if not isinstance(value, list):
        return []

    values: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            values.append(item.strip())
    return values


def _normalize_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1"}
    return False


def _normalize_confidence(value: object) -> float:
    if isinstance(value, int | float):
        return max(0.0, min(1.0, float(value)))
    return 0.5


def _normalize_control_action(value: object) -> str | None:
    action = _normalize_text(value)
    if action is None:
        return None
    normalized = action.lower().replace("_", " ")
    aliases = {
        "continue": "play",
        "resume": "play",
        "上一首": "previous",
        "下一首": "next",
        "跳过": "skip",
        "收藏": "favorite",
        "喜欢": "like",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in CONTROL_ACTIONS else None


def _complete_program_payload(
    draft: dict[str, object],
    agent_input: RadioAgentInput,
) -> dict[str, object]:
    return {
        "program_id": f"program-{uuid4().hex}",
        "title": draft.get("title") or "Clownfish Radio",
        "summary": draft.get("summary") or "A Clownfish agent-built station.",
        "context_snapshot": agent_input.context_snapshot.model_dump(mode="json"),
        "blocks": _normalize_program_blocks(draft=draft, agent_input=agent_input),
        "total_duration_minutes": agent_input.request.user_state.duration_minutes,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _normalize_program_blocks(
    draft: dict[str, object],
    agent_input: RadioAgentInput,
) -> list[dict[str, object]]:
    raw_blocks = draft.get("blocks")
    if isinstance(raw_blocks, list):
        if _looks_like_flat_item_sequence(raw_blocks):
            items = _normalize_program_items(raw_blocks, agent_input)
            return (
                [
                    _build_single_block(
                        items=items, block_title=draft.get("title"), summary=draft.get("summary")
                    )
                ]
                if items
                else []
            )

        normalized_blocks: list[dict[str, object]] = []
        for index, raw_block in enumerate(raw_blocks):
            if not isinstance(raw_block, dict):
                continue

            raw_items = raw_block.get("items")
            if not isinstance(raw_items, list):
                continue

            items = _normalize_program_items(raw_items, agent_input)
            if not items:
                continue

            normalized_blocks.append(
                {
                    "block_id": _normalize_text(raw_block.get("block_id")) or f"block-{index}",
                    "title": _normalize_text(raw_block.get("title"))
                    or _default_block_title(index=index),
                    "summary": _normalize_optional_text(raw_block.get("summary")),
                    "position": _normalize_int(raw_block.get("position"), default=index),
                    "items": items,
                }
            )

        if normalized_blocks:
            return normalized_blocks

    raw_items = draft.get("items")
    if isinstance(raw_items, list):
        items = _normalize_program_items(raw_items, agent_input)
        if items:
            return [
                _build_single_block(
                    items=items,
                    block_title=draft.get("title"),
                    summary=draft.get("summary"),
                )
            ]

    return []


def _build_single_block(
    items: list[dict[str, object]],
    block_title: object,
    summary: object,
) -> dict[str, object]:
    return {
        "block_id": "block-0",
        "title": _normalize_text(block_title) or _default_block_title(index=0),
        "summary": _normalize_optional_text(summary),
        "position": 0,
        "items": items,
    }


def _normalize_program_items(
    raw_items: list[object],
    agent_input: RadioAgentInput,
) -> list[dict[str, object]]:
    candidates_by_id = {
        candidate.candidate_id: candidate for candidate in agent_input.candidate_items
    }
    normalized_items: list[dict[str, object]] = []

    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            continue

        normalized_item = _normalize_program_item(
            raw_item=raw_item,
            position=index,
            candidates_by_id=candidates_by_id,
        )
        if normalized_item is not None:
            normalized_items.append(normalized_item)

    return normalized_items


def _normalize_program_item(
    raw_item: dict[str, object],
    position: int,
    candidates_by_id: dict[str, CandidateItem],
) -> dict[str, object] | None:
    candidate_id = _resolve_candidate_id(raw_item=raw_item, candidates_by_id=candidates_by_id)
    item_type = _resolve_item_type(
        raw_item=raw_item,
        candidate_id=candidate_id,
        candidates_by_id=candidates_by_id,
    )

    if item_type == ProgramItemType.narration.value:
        narration_text = _first_text(
            raw_item.get("narration_text"),
            raw_item.get("text"),
            raw_item.get("content"),
            raw_item.get("summary"),
            raw_item.get("title"),
        )
        if not narration_text:
            return None

        return {
            "item_id": _normalize_text(raw_item.get("item_id")) or f"item-{position}",
            "item_type": ProgramItemType.narration.value,
            "title": _normalize_text(raw_item.get("title"))
            or ("Opening" if position == 0 else f"Narration {position}"),
            "creator": None,
            "position": position,
            "candidate_id": None,
            "playback_url": None,
            "duration_seconds": None,
            "narration_text": narration_text,
            "explanation": None,
        }

    if not candidate_id:
        return None

    candidate = candidates_by_id.get(candidate_id)
    if candidate is None:
        return None

    return {
        "item_id": _normalize_text(raw_item.get("item_id")) or f"item-{position}",
        "item_type": candidate.content_type.value,
        "title": _normalize_text(raw_item.get("title")) or candidate.title,
        "creator": _normalize_text(raw_item.get("creator")) or candidate.creator,
        "position": position,
        "candidate_id": candidate.candidate_id,
        "playback_url": _normalize_text(raw_item.get("playback_url")) or candidate.playback_url,
        "duration_seconds": _normalize_int(
            raw_item.get("duration_seconds"),
            default=candidate.duration_seconds,
        ),
        "narration_text": None,
        "explanation": _first_text(
            raw_item.get("explanation"),
            raw_item.get("reason"),
            raw_item.get("why"),
        ),
    }


def _resolve_candidate_id(
    raw_item: dict[str, object],
    candidates_by_id: dict[str, CandidateItem],
) -> str | None:
    raw_candidate_id = raw_item.get("candidate_id")
    if isinstance(raw_candidate_id, str) and raw_candidate_id in candidates_by_id:
        return raw_candidate_id

    title = _normalize_text(raw_item.get("title"))
    creator = _normalize_text(raw_item.get("creator"))
    if not title:
        return None

    normalized_title = title.lower()
    normalized_creator = creator.lower() if creator else None
    for candidate in candidates_by_id.values():
        if candidate.title.lower() != normalized_title:
            continue
        if normalized_creator and candidate.creator.lower() != normalized_creator:
            continue
        return candidate.candidate_id

    return None


def _resolve_item_type(
    raw_item: dict[str, object],
    candidate_id: str | None,
    candidates_by_id: dict[str, CandidateItem],
) -> str:
    raw_type = _normalize_text(raw_item.get("item_type")) or _normalize_text(raw_item.get("type"))
    if raw_type in {ProgramItemType.narration.value, "narration"}:
        return ProgramItemType.narration.value
    if raw_type in {ProgramItemType.music.value, ProgramItemType.podcast.value}:
        return raw_type
    if raw_type in {"track", "song", "audio", "content"} and candidate_id:
        candidate = candidates_by_id.get(candidate_id)
        if candidate is not None:
            return candidate.content_type.value
    if candidate_id:
        candidate = candidates_by_id.get(candidate_id)
        if candidate is not None:
            return candidate.content_type.value
    return ProgramItemType.narration.value


def _looks_like_flat_item_sequence(raw_blocks: list[object]) -> bool:
    for raw_block in raw_blocks:
        if not isinstance(raw_block, dict):
            continue
        if "items" in raw_block:
            return False
        if {
            "type",
            "item_type",
            "candidate_id",
            "narration_text",
            "text",
        }.intersection(raw_block):
            return True
    return False


def _normalize_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _normalize_optional_text(value: object) -> str | None:
    return _normalize_text(value)


def _first_text(*values: object) -> str | None:
    for value in values:
        normalized = _normalize_text(value)
        if normalized:
            return normalized
    return None


def _normalize_int(value: object, default: int | None) -> int | None:
    return value if isinstance(value, int) else default


def _default_block_title(index: int) -> str:
    return "Opening Set" if index == 0 else f"Set {index + 1}"


def _extract_response_text(payload: dict[str, object]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    content = payload.get("content")
    if isinstance(content, list):
        chunks = []
        for part in content:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str):
                chunks.append(text)
        if chunks:
            return "".join(chunks).strip()

    output = payload.get("output")
    if isinstance(output, list):
        chunks: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue

            content = item.get("content")
            if not isinstance(content, list):
                continue

            for part in content:
                if not isinstance(part, dict):
                    continue

                text = part.get("text")
                if isinstance(text, str):
                    chunks.append(text)
                    continue

                output_json = part.get("json")
                if isinstance(output_json, dict):
                    chunks.append(json.dumps(output_json))

        if chunks:
            return "".join(chunks).strip()

    choices = payload.get("choices")
    if isinstance(choices, list):
        chunks = []
        for choice in choices:
            if not isinstance(choice, dict):
                continue

            message = choice.get("message")
            if not isinstance(message, dict):
                continue

            content = message.get("content")
            if isinstance(content, str):
                chunks.append(content)

        if chunks:
            return "".join(chunks).strip()

    raise ValueError("LLM agent response did not include output text")


def _join_base_url(base_url: str, path: str) -> str:
    normalized_base = base_url.rstrip("/")
    if normalized_base.endswith("/v1") and path.startswith("/v1/"):
        return f"{normalized_base}{path.removeprefix('/v1')}"
    return f"{normalized_base}{path}"


def _safe_snippet(text: str, limit: int = 300) -> str:
    compact = " ".join(text.split())
    return compact[:limit] if compact else "<empty response>"


def _extract_prompt_field(prompt: str, label: str) -> str:
    lines = prompt.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != label:
            continue
        for value in lines[index + 1 :]:
            stripped = value.strip()
            if stripped:
                return _shorten_text(stripped, limit=120)
        return ""
    return ""


def _extract_latest_user_message(prompt: str) -> str:
    latest = ""
    for line in prompt.splitlines():
        stripped = line.strip()
        if stripped.startswith("- user:"):
            latest = stripped.removeprefix("- user:").strip()
    return _shorten_text(latest, limit=120) if latest else ""


def _fallback_chat_router_result(message: str) -> ChatRouterResult:
    text = message.strip().lower()
    if not text:
        return ChatRouterResult(emotion="neutral", need_chat=True, confidence=0.4)

    constraints = ChatMusicConstraints(raw_query=message.strip())

    control_action = _detect_control_action(text)
    if control_action is not None:
        return ChatRouterResult(
            emotion="neutral",
            need_control=True,
            control_action=control_action,
            confidence=0.85,
        )

    if _contains_any(
        text,
        [
            "api key",
            "apikey",
            "配置",
            "设置",
            "key",
            "netease",
            "网易云",
            "anthropic",
            "fish audio",
        ],
    ):
        return ChatRouterResult(emotion="neutral", need_chat=True, confidence=0.75)

    if _contains_any(
        text,
        [
            "谁唱",
            "谁唱的",
            "是谁",
            "歌手是谁",
            "这首歌",
            "这首",
            "who sings",
            "who is singing",
            "what song",
            "artist?",
        ],
    ) and not _contains_any(text, ["来点", "来一首", "想听", "推荐"]):
        return ChatRouterResult(
            emotion="curious",
            need_info=True,
            need_chat=True,
            confidence=0.85,
        )

    emotion = _detect_emotion(text)
    if emotion is not None:
        constraints = constraints.model_copy(
            update={
                "mood": emotion,
                "energy": "low" if emotion in {"tired", "anxious"} else None,
                "scenes": ["recovery"] if emotion == "tired" else [],
                "avoid": ["high_bpm", "aggressive"] if emotion in {"tired", "anxious"} else [],
            }
        )
        return ChatRouterResult(
            emotion=emotion,
            need_chat=True,
            need_music=True,
            music_constraints=constraints,
            confidence=0.8,
        )

    if _contains_any(
        text,
        [
            "放点",
            "放一些",
            "来点",
            "来一首",
            "想听",
            "推荐",
            "歌手",
            "这首",
            "歌曲",
            "music",
            "song",
            "artist",
            "play ",
            "listen to",
            "recommend",
        ],
    ):
        return ChatRouterResult(
            emotion=emotion or "neutral",
            need_chat=True,
            need_music=True,
            music_constraints=_infer_music_constraints(message),
            confidence=0.8,
        )
    if _contains_any(
        text,
        [
            "换",
            "重生成",
            "重新生成",
            "重新",
            "调整",
            "调成",
            "更安静",
            "更热闹",
            "更轻松",
            "不要播客",
            "regenerate",
            "retune",
            "change",
            "make it",
            "no podcast",
        ],
    ):
        return ChatRouterResult(
            emotion=emotion or "neutral",
            need_chat=True,
            need_music=True,
            music_constraints=_infer_music_constraints(message),
            confidence=0.7,
        )
    return ChatRouterResult(emotion="neutral", need_chat=True, confidence=0.55)


def _detect_control_action(text: str) -> str | None:
    if _contains_any(text, ["暂停", "pause", "停一下", "先停"]):
        return "pause"
    if _contains_any(text, ["继续播放", "继续放", "播放吧", "resume", "continue"]):
        return "play"
    if _contains_any(text, ["下一首", "切歌", "跳过", "next", "skip"]):
        return "skip"
    if _contains_any(text, ["上一首", "previous", "back"]):
        return "previous"
    if _contains_any(text, ["停止播放", "stop"]):
        return "stop"
    if _contains_any(text, ["收藏", "favorite", "collect"]):
        return "favorite"
    if _contains_any(text, ["喜欢这首", "like this", "i like this"]):
        return "like"
    return None


def _detect_emotion(text: str) -> str | None:
    if _contains_any(text, ["累", "疲惫", "没精神", "tired", "exhausted", "worn out"]):
        return "tired"
    if _contains_any(text, ["焦虑", "烦", "慌", "anxious", "stress", "stressed"]):
        return "anxious"
    if _contains_any(text, ["开心", "高兴", "happy", "good mood"]):
        return "happy"
    if _contains_any(text, ["怀旧", "想以前", "nostalgic"]):
        return "nostalgic"
    if _contains_any(text, ["平静", "安静", "calm", "quiet"]):
        return "calm"
    return None


def _infer_music_constraints(message: str) -> ChatMusicConstraints:
    text = message.strip()
    lower_text = text.lower()
    constraints = ChatMusicConstraints(raw_query=text)

    artists: list[str] = []
    artist_match = re.search(
        r"(?:放点|来点|想听|播放|推荐)\s*([\u4e00-\u9fffA-Za-z0-9 ._-]{2,24})",
        text,
    )
    if artist_match:
        artist = artist_match.group(1).strip(" 的歌音乐")
        if artist and artist not in {"安静", "轻松", "中文", "日语", "英文"}:
            artists.append(artist)

    genres: list[str] = []
    if _contains_any(lower_text, ["jazz", "爵士"]):
        genres.append("jazz")
    if _contains_any(lower_text, ["民谣", "folk"]):
        genres.append("folk")
    if _contains_any(lower_text, ["摇滚", "rock"]):
        genres.append("rock")
    if _contains_any(lower_text, ["电子", "electronic"]):
        genres.append("electronic")

    languages: list[str] = []
    if _contains_any(lower_text, ["中文", "华语", "mandarin", "chinese"]):
        languages.append("Chinese")
    if _contains_any(lower_text, ["日语", "日文", "japanese"]):
        languages.append("Japanese")
    if _contains_any(lower_text, ["英文", "english"]):
        languages.append("English")

    scenes: list[str] = []
    if _contains_any(lower_text, ["雨夜", "rain", "rainy"]):
        scenes.append("rainy night")
    if _contains_any(lower_text, ["睡前", "入睡", "sleep"]):
        scenes.append("sleep")
    if _contains_any(lower_text, ["通勤", "commute"]):
        scenes.append("commute")

    mood = _detect_emotion(lower_text)
    energy = None
    avoid: list[str] = []
    if _contains_any(lower_text, ["安静", "慢", "轻一点", "quiet", "slow"]):
        mood = mood or "calm"
        energy = "low"
    if _contains_any(lower_text, ["不要播客", "no podcast"]):
        avoid.append("podcast")
    if _contains_any(lower_text, ["不要太吵", "别太吵", "not loud"]):
        avoid.append("loud")

    return constraints.model_copy(
        update={
            "artists": artists,
            "genres": genres,
            "languages": languages,
            "scenes": scenes,
            "mood": mood,
            "energy": energy,
            "avoid": avoid,
        }
    )


def _contains_any(text: str, values: list[str]) -> bool:
    return any(value in text for value in values)


def _shorten_text(text: str, limit: int = 80) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip("，。,. ") + "..."


def _candidate_rotation_key(agent_input: RadioAgentInput, candidate: CandidateItem) -> int:
    local_time = agent_input.context_snapshot.device_context.local_time.isoformat()
    latest_chat = agent_input.chat_history[-1].text if agent_input.chat_history else ""
    seed = "|".join(
        [
            agent_input.request.user_id,
            local_time,
            agent_input.request.user_state.free_text or "",
            latest_chat,
            candidate.candidate_id,
        ]
    )
    digest = hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()
    return int(digest[:10], 16)


def _language_hint(agent_input: RadioAgentInput) -> str:
    values = [
        agent_input.context_snapshot.device_context.locale or "",
        agent_input.request.user_state.free_text or "",
        *(message.text for message in agent_input.chat_history[-3:]),
    ]
    return " ".join(values)


def _prefers_chinese(value: str) -> bool:
    if "zh" in value.lower():
        return True
    chinese_count = len(re.findall(r"[\u4e00-\u9fff]", value))
    ascii_word_count = len(re.findall(r"[A-Za-z]{2,}", value))
    return chinese_count > 0 and chinese_count >= ascii_word_count


def _local_datetime(agent_input: RadioAgentInput) -> datetime:
    local_time = agent_input.context_snapshot.device_context.local_time
    if local_time.tzinfo is None:
        local_time = local_time.replace(tzinfo=UTC)

    timezone = agent_input.context_snapshot.device_context.timezone
    try:
        return local_time.astimezone(ZoneInfo(timezone))
    except ZoneInfoNotFoundError:
        return local_time


def _format_local_date(agent_input: RadioAgentInput) -> str:
    local_time = _local_datetime(agent_input)
    return local_time.strftime("%A, %B %d, %Y").replace(" 0", " ")


def _day_period(local_time: datetime) -> str:
    hour = local_time.hour
    if 5 <= hour < 12:
        return "Morning"
    if 12 <= hour < 18:
        return "Afternoon"
    if 18 <= hour < 23:
        return "Evening"
    return "Late Night"


def _city(agent_input: RadioAgentInput) -> str:
    weather_city = agent_input.context_snapshot.weather.get("city")
    if isinstance(weather_city, str) and weather_city.strip():
        return weather_city.strip()

    city_hint = agent_input.context_snapshot.device_context.city_hint
    return city_hint.strip() if city_hint else "your current city"


def _weather_text(agent_input: RadioAgentInput) -> str:
    weather = agent_input.context_snapshot.weather
    if weather.get("source") == "disabled":
        return "weather unavailable"
    condition = weather.get("condition")
    condition_text = condition if isinstance(condition, str) and condition else "unknown"
    temperature = weather.get("temperature_celsius")
    if isinstance(temperature, int | float):
        return f"{condition_text}, {temperature:g} degrees Celsius"
    return condition_text


def _station_focus(agent_input: RadioAgentInput) -> str:
    user_state = agent_input.request.user_state
    fragments: list[str] = []

    if user_state.free_text:
        fragments.append(f'the request "{user_state.free_text.strip()}"')
    if user_state.mood is not None:
        fragments.append(f"a {user_state.mood.value} mood")
    if user_state.needs:
        needs = ", ".join(need.value for need in user_state.needs)
        fragments.append(f"the need for {needs}")

    return _join_natural(fragments) if fragments else "the current moment"


def _atmosphere_text(
    agent_input: RadioAgentInput,
    selected_candidates: list[CandidateItem],
) -> str:
    descriptors: list[str] = []
    user_state = agent_input.request.user_state

    if user_state.mood is not None:
        descriptors.append(user_state.mood.value)
    descriptors.extend(need.value for need in user_state.needs)

    for candidate in selected_candidates:
        descriptors.extend(_public_tags(candidate))

    unique_descriptors = _unique(descriptors)[:4]
    if not unique_descriptors:
        return "personal and present"

    return _join_natural(unique_descriptors)


def _track_list(candidates: list[CandidateItem]) -> str:
    if not candidates:
        return "a few available tracks"

    tracks = [f"{candidate.title} by {candidate.creator}" for candidate in candidates[:3]]
    if len(candidates) > 3:
        tracks.append(f"{len(candidates) - 3} more")
    return _join_natural(tracks)


def _tag_text(candidate: CandidateItem) -> str:
    tags = _public_tags(candidate)
    if not tags:
        return f"a playable source from {candidate.source}"
    return _join_natural(tags[:3])


def _public_tags(candidate: CandidateItem) -> list[str]:
    technical_tags = {"netease", "real_playback"}
    return [tag for tag in candidate.tags if tag.lower() not in technical_tags]


def _tokenize(text: str | None) -> list[str]:
    if not text:
        return []
    raw_tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9][a-zA-Z0-9'_-]+", text.lower())
    return [token for token in raw_tokens if len(token) >= 2]


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        normalized = value.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_values.append(value.strip())
    return unique_values


def _join_natural(values: list[str]) -> str:
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])}, and {values[-1]}"
