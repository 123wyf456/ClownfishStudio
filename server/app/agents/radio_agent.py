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


@dataclass(frozen=True)
class RadioAgentInput:
    request: GenerateProgramRequest
    context_snapshot: ContextSnapshot
    memory: UserMusicMemory
    history: list[dict[str, str]]
    candidate_items: list[CandidateItem]
    prompt: str


class RadioModelClient(Protocol):
    def generate_program(self, agent_input: RadioAgentInput) -> dict[str, object]:
        """Return a raw RadioProgram-compatible payload."""


class ModelRequestError(ValueError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class MockRadioModelClient:
    """Deterministic local agent used when no model key is configured.

    It still behaves like an agent boundary: tools provide facts and playable
    candidates, then this runtime decides the program shape and narration from
    those materials without inventing songs.
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
        scored_candidates = [
            (self._score_candidate(agent_input, candidate), index, candidate)
            for index, candidate in enumerate(agent_input.candidate_items)
        ]
        scored_candidates.sort(key=lambda item: (-item[0], item[1]))
        return [candidate for _, _, candidate in scored_candidates[:target_count]]

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
        date_text = _format_local_date(agent_input)
        city = _city(agent_input)
        weather = _weather_text(agent_input)
        station_focus = _station_focus(agent_input)
        atmosphere = _atmosphere_text(agent_input, selected_candidates)
        track_list = _track_list(selected_candidates)

        return (
            "Hi, I am Clownfish, your personal radio agent. "
            f"Today is {date_text}. I am reading your city as {city}; "
            f"the current weather is {weather}. "
            f"For this session, I am shaping the station around {station_focus}. "
            f"I will start with {track_list}. "
            f"The set is meant to feel {atmosphere}, so it should give the room "
            "a little more presence than a plain playlist."
        )

    def _build_bridge(
        self,
        agent_input: RadioAgentInput,
        previous_candidate: CandidateItem,
        next_candidate: CandidateItem,
    ) -> str:
        atmosphere = _atmosphere_text(agent_input, [previous_candidate, next_candidate])
        next_tags = _tag_text(next_candidate)
        return (
            f"After {previous_candidate.title}, I am moving into "
            f"{next_candidate.title} by {next_candidate.creator}. "
            f"This keeps the station {atmosphere}, with {next_tags} giving "
            "the next few minutes a slightly different texture."
        )

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
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")

    def generate_program(self, agent_input: RadioAgentInput) -> dict[str, object]:
        try:
            payload = self._post_json("/responses", self._build_responses_body(agent_input))
        except ModelRequestError as exc:
            if not _should_try_chat_completions_fallback(exc):
                raise
            payload = self._post_json(
                "/chat/completions",
                self._build_chat_completions_body(agent_input),
            )

        draft = _load_response_json(payload)
        return _complete_program_payload(draft=draft, agent_input=agent_input)

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
            with urlopen(request, timeout=120) as response:
                raw_text = response.read().decode("utf-8", errors="replace")
                try:
                    payload = json.loads(raw_text)
                except json.JSONDecodeError as exc:
                    raise ModelRequestError(
                        f"Codex agent response was not JSON: {_safe_snippet(raw_text)}"
                    ) from exc
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ModelRequestError(
                f"Codex agent request failed: {exc.code} {_safe_snippet(detail)}",
                status_code=exc.code,
            ) from exc
        except URLError as exc:
            raise ModelRequestError(f"Codex agent request failed: {exc.reason}") from exc

        if not isinstance(payload, dict):
            raise ModelRequestError("Codex agent response must be a JSON object")

        return payload


def _should_try_chat_completions_fallback(exc: ModelRequestError) -> bool:
    if exc.status_code in {401, 403}:
        return False
    return True


def _load_response_json(payload: dict[str, object]) -> dict[str, object]:
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        raise ValueError(
            f"Codex agent request failed: {message if isinstance(message, str) else error}"
        )

    text = _extract_response_text(payload)

    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("Codex agent returned non-JSON output") from exc

    if not isinstance(loaded, dict):
        raise ValueError("Codex agent output must be a JSON object")

    return loaded


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

    raise ValueError("Codex agent response did not include output text")


def _safe_snippet(text: str, limit: int = 300) -> str:
    compact = " ".join(text.split())
    return compact[:limit] if compact else "<empty response>"


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
