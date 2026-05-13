from __future__ import annotations

import re
from uuid import uuid4

from app.agents import RadioAgentRuntime, SongRequestPlanner, build_song_request_planner
from app.schemas import (
    CandidateItem,
    GenerateProgramRequest,
    GenerateProgramResponse,
    UserMusicMemory,
)
from app.services.providers import build_calendar_provider, build_weather_provider
from app.tools import (
    get_netease_personalized_candidates,
    get_netease_preference_candidates,
    get_recent_history,
    get_user_music_memory,
    list_memory_update_hints,
    save_program,
    save_program_history,
    search_music_candidates,
    search_podcast_candidates,
)
from app.tools.netease_music_tool import is_netease_music_enabled

AVOIDANCE_HINT_ACTIONS = {"decrease_affinity", "reduce_repetition", "record_skip"}
NEGATIVE_PODCAST_KEYWORDS = (
    "no podcast",
    "without podcast",
    "music only",
    "skip podcast",
    "\u4e0d\u8981\u64ad\u5ba2",
    "\u522b\u64ad\u64ad\u5ba2",
    "\u4e0d\u8981podcast",
    "\u4e0d\u8981\u8bbf\u8c08",
)
POSITIVE_PODCAST_KEYWORDS = (
    "podcast",
    "talk show",
    "interview",
    "spoken audio",
    "\u64ad\u5ba2",
    "\u8bbf\u8c08",
    "\u804a\u5929",
)
MOOD_QUERY_HINTS: dict[str, tuple[str, ...]] = {
    "calm": ("calm", "gentle", "chill", "\u5b89\u9759", "\u8212\u7f13"),
    "tired": ("relax", "soft", "recovery", "\u653e\u677e", "\u6062\u590d"),
    "focused": ("focus", "lofi", "instrumental", "\u4e13\u6ce8", "\u5b66\u4e60"),
    "happy": ("bright", "groove", "uplifting", "\u660e\u4eae", "\u8f7b\u5feb"),
    "anxious": ("ambient", "calming", "decompression", "\u51cf\u538b", "\u8212\u7f13"),
    "nostalgic": ("nostalgic", "oldies", "retro", "\u6000\u65e7", "\u590d\u53e4"),
}
NEED_QUERY_HINTS: dict[str, tuple[str, ...]] = {
    "relax": ("relax", "chill", "night", "\u653e\u677e", "\u591c\u665a"),
    "focus": ("focus", "lofi", "study", "\u4e13\u6ce8", "\u5b66\u4e60"),
    "commute": ("commute", "city pop", "drive", "\u901a\u52e4"),
    "workout": ("workout", "power", "high energy", "\u8fd0\u52a8"),
    "sleep": ("sleep", "ambient", "soft", "\u52a9\u7720", "\u67d4\u548c"),
    "discover": ("discovery", "new discovery", "new music", "\u53d1\u73b0", "\u65b0\u6b4c"),
    "companionship": (
        "companionship",
        "night radio",
        "warm voice",
        "\u966a\u4f34",
        "\u6df1\u591c\u7535\u53f0",
    ),
}
WEATHER_QUERY_HINTS: dict[str, tuple[str, ...]] = {
    "rain": ("rainy night", "rain", "soft", "\u96e8\u591c"),
    "drizzle": ("rainy night", "drizzle", "soft", "\u7ec6\u96e8"),
    "thunderstorm": ("storm", "late night", "\u96f7\u96e8"),
    "snow": ("winter night", "soft", "\u51ac\u591c"),
    "clear": ("night", "night breeze", "\u665a\u98ce"),
    "clouds": ("cloudy", "downtempo", "\u9634\u5929"),
}


class ProgramGenerationService:
    def __init__(
        self,
        runtime: RadioAgentRuntime | None = None,
        song_request_planner: SongRequestPlanner | None = None,
    ) -> None:
        self._runtime = runtime or RadioAgentRuntime()
        self._song_request_planner = song_request_planner or build_song_request_planner()
        self._weather_provider = build_weather_provider()
        self._calendar_provider = build_calendar_provider()

    def generate(self, request: GenerateProgramRequest) -> GenerateProgramResponse:
        weather = self._weather_provider.get_weather(request.device_context.city_hint)
        calendar_events = self._calendar_provider.get_events(request.user_id)
        memory = get_user_music_memory(request.user_id)
        history = [
            *_feedback_hints_to_history(request.user_id),
            *get_recent_history(request.user_id, limit=max(20, request.max_candidates * 3)),
        ]
        candidate_items, warnings = self._collect_candidates(
            request=request,
            memory=memory,
            history=history,
            weather=weather,
        )

        program = self._runtime.generate_program(
            request=request,
            weather=weather,
            calendar_events=calendar_events,
            memory=memory,
            history=history,
            candidate_items=candidate_items,
        )
        save_program(program)
        save_program_history(user_id=request.user_id, program=program)

        return GenerateProgramResponse(
            request_id=f"request-{uuid4().hex}",
            program=program,
            candidate_count=len(candidate_items),
            warnings=warnings,
        )

    def _collect_candidates(
        self,
        request: GenerateProgramRequest,
        memory: UserMusicMemory | None = None,
        history: list[dict[str, str]] | None = None,
        weather: dict[str, str | int | float | bool | None] | None = None,
    ) -> tuple[list[CandidateItem], list[str]]:
        resolved_memory = memory or get_user_music_memory(request.user_id)
        resolved_history = history or get_recent_history(
            request.user_id,
            limit=max(20, request.max_candidates * 3),
        )
        resolved_weather = weather or self._weather_provider.get_weather(
            request.device_context.city_hint
        )

        tags = _requested_tags(request)
        music_limit, podcast_limit = _candidate_mix(request)
        request_plan = self._song_request_planner.plan(
            message=request.user_state.free_text or "",
            memory=resolved_memory,
            weather=resolved_weather,
        )
        query_plan = _build_music_query_plan(
            request=request,
            memory=resolved_memory,
            weather=resolved_weather,
            request_plan=request_plan,
        )
        avoid_candidate_ids = _recent_candidate_ids(
            memory=resolved_memory,
            history=resolved_history,
        )
        recent_creators = _recent_creators(resolved_history)
        has_targeting = bool(query_plan or tags)

        preference_candidates = get_netease_preference_candidates(limit=max(8, music_limit))
        personalized_candidates = get_netease_personalized_candidates(limit=max(8, music_limit))

        targeted_music_candidates: list[CandidateItem] = []
        per_query_limit = max(4, min(6, music_limit))
        for query in query_plan[:5]:
            targeted_music_candidates.extend(
                _tag_search_candidates(
                    search_music_candidates(query=query, tags=tags, limit=per_query_limit),
                    requested_tags=tags,
                    search_query=query,
                )
            )

        fallback_music_candidates: list[CandidateItem] = []
        if (
            len(preference_candidates)
            + len(personalized_candidates)
            + len(targeted_music_candidates)
            < music_limit
        ):
            for query in _build_fallback_music_queries(
                request=request,
                memory=resolved_memory,
                weather=resolved_weather,
            ):
                fallback_music_candidates.extend(
                    _tag_search_candidates(
                        search_music_candidates(query=query, limit=per_query_limit),
                        requested_tags=tags,
                        search_query=query,
                        extra_tags=["fallback_search"],
                    )
                )

        music_candidates = _prioritize_candidate_pool(
            [
                *preference_candidates,
                *personalized_candidates,
                *targeted_music_candidates,
                *fallback_music_candidates,
            ],
            avoid_candidate_ids=avoid_candidate_ids,
            recent_creators=recent_creators,
            limit=music_limit,
            preferred_title=request_plan.preferred_title,
            preferred_artist=request_plan.preferred_artist,
        )

        if not music_candidates:
            broad_music_pool = _tag_search_candidates(
                search_music_candidates(limit=max(music_limit, request.max_candidates)),
                requested_tags=tags,
                search_query="broad fallback",
                extra_tags=["broad_fallback"],
            )
            broad_music_candidates = [
                candidate
                for candidate in broad_music_pool
                if candidate.candidate_id not in avoid_candidate_ids
            ]
            if not broad_music_candidates:
                broad_music_candidates = broad_music_pool
            music_candidates = _prioritize_candidate_pool(
                broad_music_candidates,
                avoid_candidate_ids=avoid_candidate_ids,
                recent_creators=recent_creators,
                limit=music_limit,
                preferred_title=request_plan.preferred_title,
                preferred_artist=request_plan.preferred_artist,
            )

        podcast_candidates: list[CandidateItem] = []
        if podcast_limit > 0:
            podcast_query = request.user_state.free_text
            targeted_podcast_candidates = (
                search_podcast_candidates(query=podcast_query, tags=tags, limit=podcast_limit)
                if podcast_query or tags
                else []
            )
            fallback_podcast_candidates = (
                search_podcast_candidates(limit=podcast_limit)
                if len(targeted_podcast_candidates) < podcast_limit
                else []
            )
            podcast_candidates = _prioritize_candidate_pool(
                [*targeted_podcast_candidates, *fallback_podcast_candidates],
                avoid_candidate_ids=avoid_candidate_ids,
                recent_creators=recent_creators,
                limit=podcast_limit,
            )

        candidate_items = _deduplicate_candidates(
            [*music_candidates, *podcast_candidates],
            limit=request.max_candidates,
        )

        warnings: list[str] = []
        if has_targeting and not (
            preference_candidates or personalized_candidates or targeted_music_candidates
        ):
            warnings.append(
                "No personalized or targeted music candidates matched; used fallback results."
            )
        if not candidate_items:
            warnings.append("No candidate content is available; radio generation cannot continue.")

        return candidate_items, warnings


def _deduplicate_candidates(candidates: list[CandidateItem], limit: int) -> list[CandidateItem]:
    deduplicated: list[CandidateItem] = []
    seen_candidate_ids: set[str] = set()

    for candidate in candidates:
        if candidate.candidate_id in seen_candidate_ids:
            continue

        deduplicated.append(candidate)
        seen_candidate_ids.add(candidate.candidate_id)
        if len(deduplicated) >= limit:
            break

    return deduplicated


def _requested_tags(request: GenerateProgramRequest) -> list[str]:
    tags = [need.value for need in request.user_state.needs]
    if request.user_state.mood is not None:
        tags.append(request.user_state.mood.value)
    return _unique_strings(tags)


def _candidate_mix(request: GenerateProgramRequest) -> tuple[int, int]:
    wants_podcasts = _should_include_podcasts(request)
    music_share = 0.7 if wants_podcasts else 1.0
    music_limit = max(1, round(request.max_candidates * music_share))
    podcast_limit = max(0, request.max_candidates - music_limit)
    return music_limit, podcast_limit


def _should_include_podcasts(request: GenerateProgramRequest) -> bool:
    free_text = (request.user_state.free_text or "").strip().lower()
    if free_text and any(keyword in free_text for keyword in NEGATIVE_PODCAST_KEYWORDS):
        return False
    if free_text and any(keyword in free_text for keyword in POSITIVE_PODCAST_KEYWORDS):
        return True
    return False


def _build_music_query_plan(
    request: GenerateProgramRequest,
    memory: UserMusicMemory,
    weather: dict[str, str | int | float | bool | None],
    request_plan: object,
) -> list[str]:
    free_text = _normalize_query(request.user_state.free_text)
    explicit_query = (
        request_plan.search_queries[0]
        if getattr(request_plan, "search_queries", None)
        else _extract_explicit_music_query(request.user_state.free_text)
    )
    descriptor_terms = _descriptor_terms(request=request, weather=weather)
    favorite_genres = memory.favorite_genres[:3]
    favorite_artists = memory.favorite_artists[:3]
    preferred_title = request_plan.preferred_title
    preferred_artist = request_plan.preferred_artist
    preferred_tags = request_plan.preferred_tags[:3]

    queries: list[str | None] = [
        *request_plan.search_queries[:4],
        explicit_query,
        free_text,
        _join_query_parts(preferred_title, preferred_artist),
        _join_query_parts(preferred_title, preferred_tags[:2]),
        _join_query_parts(preferred_artist, preferred_tags[:2]),
        _join_query_parts(explicit_query, descriptor_terms[:2]),
        _join_query_parts(explicit_query, favorite_genres[:1]),
        _join_query_parts(explicit_query, favorite_artists[:1]),
        _join_query_parts(free_text, descriptor_terms[:2]),
        _join_query_parts(descriptor_terms[:3]),
        _join_query_parts(favorite_genres[:2]),
        _join_query_parts(descriptor_terms[:2], favorite_genres[:1]),
        _join_query_parts(descriptor_terms[:2], favorite_artists[:1]),
    ]
    return _unique_strings(query for query in queries if query)


def _build_fallback_music_queries(
    request: GenerateProgramRequest,
    memory: UserMusicMemory,
    weather: dict[str, str | int | float | bool | None],
) -> list[str]:
    descriptor_terms = _descriptor_terms(request=request, weather=weather)
    favorite_genres = memory.favorite_genres[:2]
    favorite_artists = memory.favorite_artists[:2]

    queries: list[str | None] = [
        _join_query_parts(descriptor_terms[:2], favorite_genres[:1]),
        _join_query_parts(descriptor_terms[:2], favorite_artists[:1]),
        _join_query_parts(favorite_genres[:2]),
        _join_query_parts(favorite_artists[:1]),
        _fallback_music_query(weather=weather),
    ]
    return _unique_strings(query for query in queries if query)


def _descriptor_terms(
    request: GenerateProgramRequest,
    weather: dict[str, str | int | float | bool | None],
) -> list[str]:
    terms: list[str] = []
    if request.user_state.mood is not None:
        terms.extend(MOOD_QUERY_HINTS.get(request.user_state.mood.value, ()))
    for need in request.user_state.needs:
        terms.extend(NEED_QUERY_HINTS.get(need.value, ()))

    condition = weather.get("condition")
    if isinstance(condition, str):
        terms.extend(WEATHER_QUERY_HINTS.get(condition.lower(), ()))

    local_hour = request.device_context.local_time.hour
    if 22 <= local_hour or local_hour < 5:
        terms.extend(("late night", "\u6df1\u591c"))

    return _unique_strings(terms)


def _recent_candidate_ids(
    memory: UserMusicMemory,
    history: list[dict[str, str]],
) -> set[str]:
    return {
        candidate_id
        for candidate_id in [
            *memory.recent_candidate_ids,
            *(event.get("candidate_id", "") for event in history),
        ]
        if candidate_id
    }


def _recent_creators(history: list[dict[str, str]]) -> set[str]:
    creators: set[str] = set()
    for event in history:
        raw_creator = event.get("creator", "")
        if not raw_creator:
            continue
        creators.update(_creator_fragments(raw_creator))
    return creators


def _tag_search_candidates(
    candidates: list[CandidateItem],
    requested_tags: list[str],
    search_query: str,
    extra_tags: list[str] | None = None,
) -> list[CandidateItem]:
    tagged_candidates: list[CandidateItem] = []
    for candidate in candidates:
        tags = _unique_strings(
            [
                *candidate.tags,
                *requested_tags,
                *(extra_tags or []),
                "query_match",
            ]
        )
        metadata = {
            **candidate.metadata,
            "search_query": search_query,
        }
        tagged_candidates.append(candidate.model_copy(update={"tags": tags, "metadata": metadata}))
    return tagged_candidates


def _prioritize_candidate_pool(
    candidates: list[CandidateItem],
    avoid_candidate_ids: set[str],
    recent_creators: set[str],
    limit: int,
    preferred_title: str | None = None,
    preferred_artist: str | None = None,
) -> list[CandidateItem]:
    if limit <= 0:
        return []

    deduplicated = _deduplicate_candidates(candidates, limit=len(candidates))
    fresh_candidates = [
        candidate for candidate in deduplicated if candidate.candidate_id not in avoid_candidate_ids
    ]
    avoided_candidates = [
        candidate for candidate in deduplicated if candidate.candidate_id in avoid_candidate_ids
    ]
    sorted_fresh_candidates = _sort_candidates_for_priority(
        fresh_candidates,
        preferred_title=preferred_title,
        preferred_artist=preferred_artist,
    )
    sorted_avoided_candidates = _sort_candidates_for_priority(
        avoided_candidates,
        preferred_title=preferred_title,
        preferred_artist=preferred_artist,
    )
    selected = _select_diverse_candidates(
        sorted_fresh_candidates,
        recent_creators=recent_creators,
        limit=limit,
    )
    if len(selected) < limit:
        selected.extend(
            _select_diverse_candidates(
                sorted_avoided_candidates,
                recent_creators=recent_creators,
                limit=limit - len(selected),
                seen_candidate_ids={candidate.candidate_id for candidate in selected},
                seen_creators={
                    creator
                    for candidate in selected
                    for creator in _creator_fragments(candidate.creator)
                },
            )
        )
    return selected[:limit]


def _sort_candidates_for_priority(
    candidates: list[CandidateItem],
    preferred_title: str | None = None,
    preferred_artist: str | None = None,
) -> list[CandidateItem]:
    def score(candidate: CandidateItem) -> tuple[int, int, int]:
        candidate_tags = {tag.lower() for tag in candidate.tags}
        title_priority = _match_priority(candidate.title, preferred_title)
        artist_priority = _match_priority(candidate.creator, preferred_artist)
        query_priority = 1 if "query_match" in candidate_tags else 0
        preference_priority = 1 if "user_preference" in candidate_tags else 0
        playback_priority = 1 if candidate.playback_url else 0
        return (
            title_priority,
            artist_priority,
            query_priority,
            preference_priority,
            playback_priority,
        )

    return sorted(candidates, key=score, reverse=True)


def _match_priority(value: str, target: str | None) -> int:
    if not target:
        return 0
    normalized_value = value.strip().lower()
    normalized_target = target.strip().lower()
    if not normalized_value or not normalized_target:
        return 0
    if normalized_value == normalized_target:
        return 3
    if normalized_target in normalized_value:
        return 2
    value_tokens = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", normalized_value))
    target_tokens = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", normalized_target))
    if value_tokens and target_tokens and value_tokens.intersection(target_tokens):
        return 1
    return 0


def _select_diverse_candidates(
    candidates: list[CandidateItem],
    recent_creators: set[str],
    limit: int,
    seen_candidate_ids: set[str] | None = None,
    seen_creators: set[str] | None = None,
) -> list[CandidateItem]:
    if limit <= 0:
        return []

    selected: list[CandidateItem] = []
    candidate_ids = set(seen_candidate_ids or set())
    creator_keys = set(seen_creators or set())
    prioritized = [
        *[
            candidate
            for candidate in candidates
            if not _is_recent_creator(candidate, recent_creators)
        ],
        *[
            candidate
            for candidate in candidates
            if _is_recent_creator(candidate, recent_creators)
        ],
    ]
    backlog: list[CandidateItem] = []

    for candidate in prioritized:
        if candidate.candidate_id in candidate_ids:
            continue
        creators = _creator_fragments(candidate.creator)
        if creators and creators.intersection(creator_keys):
            backlog.append(candidate)
            continue

        selected.append(candidate)
        candidate_ids.add(candidate.candidate_id)
        creator_keys.update(creators)
        if len(selected) >= limit:
            return selected

    for candidate in backlog:
        if candidate.candidate_id in candidate_ids:
            continue
        selected.append(candidate)
        candidate_ids.add(candidate.candidate_id)
        if len(selected) >= limit:
            break

    return selected


def _is_recent_creator(candidate: CandidateItem, recent_creators: set[str]) -> bool:
    return bool(_creator_fragments(candidate.creator).intersection(recent_creators))


def _creator_fragments(creator: str) -> set[str]:
    return {
        fragment.strip().lower()
        for fragment in re.split(r"[,&/]|feat\\.|Feat\\.|FEAT\\.", creator)
        if fragment.strip()
    }


def _feedback_hints_to_history(user_id: str) -> list[dict[str, str]]:
    hints = list_memory_update_hints(user_id=user_id, actions=AVOIDANCE_HINT_ACTIONS)
    history: list[dict[str, str]] = []

    for index, hint in enumerate(hints):
        candidate_id = hint.get("candidate_id")
        if not candidate_id:
            continue
        history.append(
            {
                "event_id": f"feedback-hint-{index}",
                "user_id": user_id,
                "candidate_id": candidate_id,
                "event_type": hint.get("action", "feedback_hint"),
                "occurred_at": "",
            }
        )

    return history


def _fallback_music_query(
    weather: dict[str, str | int | float | bool | None],
) -> str | None:
    if not is_netease_music_enabled():
        return None

    condition = weather.get("condition")
    if isinstance(condition, str) and condition.lower() in {"rain", "drizzle"}:
        return "\u96e8\u591c \u8212\u7f13"
    if isinstance(condition, str) and condition.lower() == "snow":
        return "\u51ac\u591c \u67d4\u548c"
    return "\u6df1\u591c \u653e\u677e"


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
    return " ".join(_unique_strings(parts)) or None


def _normalize_query(value: str | None) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _extract_explicit_music_query(value: str | None) -> str | None:
    text = _normalize_query(value)
    if text is None:
        return None

    patterns = [
        r"(?:play|listen to|search for|find|recommend)\s+(.{2,48})",
        r"(?:\u60f3\u542c|\u64ad\u653e|\u641c\u7d22|\u627e\u4e00\u4e0b|\u5e2e\u6211\u627e|\u6765\u70b9|\u6765\u4e00\u70b9|\u63a8\u8350)(.{2,48})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match and match.group(1):
            return _clean_search_query(_strip_filler_words(match.group(1)))

    if len(text) <= 24 and not _looks_like_boot_instruction(text):
        return _clean_search_query(_strip_filler_words(text))

    return None


def _strip_filler_words(value: str) -> str:
    stripped = re.sub(
        r"\b(?:some|music|songs?|tracks?|please|for me|a bit|kind of)\b",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    stripped = re.sub(
        r"(?:\u4e00\u70b9|\u4e00\u4e9b|\u4e00\u9996|\u51e0\u9996|\u70b9|\u7684|\u6b4c|\u97f3\u4e50|\u5427|\u53ef\u4ee5\u5417|\u5e2e\u6211)",
        " ",
        stripped,
    )
    return stripped


def _clean_search_query(value: str) -> str:
    cleaned = re.sub(
        r"[\u3001\u3002\uff0c\uff01\uff1f\uff1b\uff1a,.!?;:\"'`~()[\]{}<>]",
        " ",
        value,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _looks_like_boot_instruction(value: str) -> bool:
    lower = value.lower()
    return any(
        phrase in lower
        for phrase in (
            "open clownfishstudio",
            "greet me",
            "current weather",
            "listening context",
            "fresh station",
        )
    )


def _unique_strings(values: object) -> list[str]:
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
