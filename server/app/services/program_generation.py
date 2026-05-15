from __future__ import annotations

import logging
import re
from time import monotonic
from uuid import uuid4

from app.agents import (
    AgentOutputValidationError,
    MockRadioModelClient,
    MockSongRequestPlanner,
    RadioAgentInput,
    RadioAgentRuntime,
    SongRequestPlanner,
    build_song_request_planner,
)
from app.schemas import (
    CalendarEvent,
    CandidateItem,
    ChatMessage,
    ContextSnapshot,
    GenerateProgramRequest,
    GenerateProgramResponse,
    RadioProgram,
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
LOGGER = logging.getLogger(__name__)


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

    def generate(
        self,
        request: GenerateProgramRequest,
        chat_history: list[ChatMessage] | None = None,
    ) -> GenerateProgramResponse:
        timings: dict[str, float] = {}
        started_at = monotonic()
        weather = self._weather_provider.get_weather(request.device_context)
        timings["weather"] = monotonic() - started_at
        step_started_at = monotonic()
        calendar_events = self._calendar_provider.get_events(request.user_id)
        timings["calendar"] = monotonic() - step_started_at
        step_started_at = monotonic()
        memory = get_user_music_memory(request.user_id)
        timings["memory"] = monotonic() - step_started_at
        step_started_at = monotonic()
        history = [
            *_feedback_hints_to_history(request.user_id),
            *get_recent_history(request.user_id, limit=max(20, request.max_candidates * 3)),
        ]
        timings["history"] = monotonic() - step_started_at
        step_started_at = monotonic()
        candidate_items, warnings, candidate_timings = self._collect_candidates(
            request=request,
            memory=memory,
            history=history,
            weather=weather,
            chat_history=chat_history,
            include_timings=True,
        )
        timings["candidates"] = monotonic() - step_started_at
        timings.update({f"candidates.{key}": value for key, value in candidate_timings.items()})

        step_started_at = monotonic()
        program, agent_warning = self._generate_program_with_fallback(
            request=request,
            weather=weather,
            calendar_events=calendar_events,
            memory=memory,
            history=history,
            candidate_items=candidate_items,
            chat_history=chat_history or [],
        )
        timings["agent"] = monotonic() - step_started_at
        step_started_at = monotonic()
        save_program(program)
        save_program_history(user_id=request.user_id, program=program)
        timings["persistence"] = monotonic() - step_started_at
        timings["total"] = monotonic() - started_at
        LOGGER.info(
            "program_generation_timing user_id=%s candidate_count=%s timings=%s",
            request.user_id,
            len(candidate_items),
            {key: round(value, 3) for key, value in timings.items()},
        )

        return GenerateProgramResponse(
            request_id=f"request-{uuid4().hex}",
            program=program,
            candidate_count=len(candidate_items),
            warnings=[*warnings, *([agent_warning] if agent_warning else [])],
        )

    def _generate_program_with_fallback(
        self,
        *,
        request: GenerateProgramRequest,
        weather: dict[str, str | int | float | bool | None],
        calendar_events: list[CalendarEvent],
        memory: UserMusicMemory,
        history: list[dict[str, str]],
        candidate_items: list[CandidateItem],
        chat_history: list[ChatMessage],
    ) -> tuple[RadioProgram, str | None]:
        try:
            return (
                self._runtime.generate_program(
                    request=request,
                    weather=weather,
                    calendar_events=calendar_events,
                    memory=memory,
                    history=history,
                    candidate_items=candidate_items,
                    chat_history=chat_history,
                ),
                None,
            )
        except Exception as exc:
            if isinstance(exc, AgentOutputValidationError) and not candidate_items:
                raise
            LOGGER.warning(
                "radio_agent_failed user_id=%s error=%s",
                request.user_id,
                exc,
            )
            context_snapshot = ContextSnapshot(
                device_context=request.device_context,
                user_state=request.user_state,
                weather=weather,
                calendar_events=calendar_events,
            )
            agent_input = RadioAgentInput(
                request=request,
                context_snapshot=context_snapshot,
                memory=memory,
                history=history,
                candidate_items=candidate_items,
                chat_history=chat_history,
                prompt="fallback",
            )
            raw_program = MockRadioModelClient().generate_program(agent_input)
            return (
                RadioProgram.model_validate(raw_program),
                "Radio agent timed out or returned invalid output; "
                "used a local fallback for this request.",
            )

    def _collect_candidates(
        self,
        request: GenerateProgramRequest,
        memory: UserMusicMemory | None = None,
        history: list[dict[str, str]] | None = None,
        weather: dict[str, str | int | float | bool | None] | None = None,
        chat_history: list[ChatMessage] | None = None,
        include_timings: bool = False,
    ) -> (
        tuple[list[CandidateItem], list[str]]
        | tuple[list[CandidateItem], list[str], dict[str, float]]
    ):
        timings: dict[str, float] = {}
        started_at = monotonic()
        resolved_memory = memory or get_user_music_memory(request.user_id)
        resolved_history = history or get_recent_history(
            request.user_id,
            limit=max(20, request.max_candidates * 3),
        )
        resolved_weather = weather or self._weather_provider.get_weather(request.device_context)

        tags = _requested_tags(request)
        music_limit, podcast_limit = _candidate_mix(request)
        step_started_at = monotonic()
        planner_warnings: list[str] = []
        if _can_use_local_request_plan(request.user_state.free_text or ""):
            request_plan = MockSongRequestPlanner().plan(
                message=request.user_state.free_text or "",
                memory=resolved_memory,
                weather=resolved_weather,
                device_context=request.device_context,
                user_state=request.user_state,
                history=resolved_history,
                chat_history=chat_history,
            )
        else:
            try:
                request_plan = self._song_request_planner.plan(
                    message=request.user_state.free_text or "",
                    memory=resolved_memory,
                    weather=resolved_weather,
                    device_context=request.device_context,
                    user_state=request.user_state,
                    history=resolved_history,
                    chat_history=chat_history,
                )
            except Exception as exc:
                LOGGER.warning(
                    "song_request_planner_failed user_id=%s error=%s",
                    request.user_id,
                    exc,
                )
                planner_warnings.append(
                    "Song request agent returned an invalid plan; "
                    "used a local fallback for this request."
                )
                request_plan = MockSongRequestPlanner().plan(
                    message=request.user_state.free_text or "",
                    memory=resolved_memory,
                    weather=resolved_weather,
                    device_context=request.device_context,
                    user_state=request.user_state,
                    history=resolved_history,
                    chat_history=chat_history,
                )
        timings["request_planner"] = monotonic() - step_started_at
        query_plan = _build_music_query_plan(request_plan=request_plan)
        avoid_candidate_ids = _recent_candidate_ids(
            memory=resolved_memory,
            history=resolved_history,
        )
        recent_creators = _recent_creators(resolved_history)
        has_targeting = bool(query_plan or tags)
        is_strict_targeting = request_plan.mode in {"artist_focus", "precise_song"}

        targeted_music_candidates: list[CandidateItem] = []
        per_query_limit = _per_query_limit(mode=request_plan.mode, music_limit=music_limit)
        step_started_at = monotonic()
        for query in query_plan[: _query_batch_limit(request_plan.mode)]:
            batch_candidates = _tag_search_candidates(
                search_music_candidates(query=query, tags=tags, limit=per_query_limit),
                requested_tags=tags,
                search_query=query,
            )
            targeted_music_candidates = _deduplicate_candidates(
                [*targeted_music_candidates, *batch_candidates],
                limit=music_limit,
            )
            filtered_targeted_candidates = _filter_targeted_candidates(
                targeted_music_candidates,
                preferred_title=request_plan.preferred_title,
                preferred_artist=request_plan.preferred_artist,
                mode=request_plan.mode,
            )
            if len(filtered_targeted_candidates) >= _targeted_batch_goal(
                mode=request_plan.mode,
                music_limit=music_limit,
            ):
                targeted_music_candidates = filtered_targeted_candidates
                break
        timings["targeted_music_search"] = monotonic() - step_started_at

        targeted_music_candidates = _filter_targeted_candidates(
            targeted_music_candidates,
            preferred_title=request_plan.preferred_title,
            preferred_artist=request_plan.preferred_artist,
            mode=request_plan.mode,
        )

        remaining_music_slots = max(0, music_limit - len(targeted_music_candidates))
        step_started_at = monotonic()
        preference_candidates = (
            []
            if is_strict_targeting or remaining_music_slots <= 0
            else get_netease_preference_candidates(limit=max(4, remaining_music_slots))
        )
        timings["preference_candidates"] = monotonic() - step_started_at
        step_started_at = monotonic()
        personalized_candidates = (
            []
            if is_strict_targeting
            or len(targeted_music_candidates) + len(preference_candidates) >= music_limit
            else get_netease_personalized_candidates(
                limit=max(
                    4,
                    music_limit - len(targeted_music_candidates) - len(preference_candidates),
                )
            )
        )
        timings["personalized_candidates"] = monotonic() - step_started_at

        fallback_music_candidates: list[CandidateItem] = []
        step_started_at = monotonic()
        if (
            len(preference_candidates)
            + len(personalized_candidates)
            + len(targeted_music_candidates)
            < music_limit
            and not is_strict_targeting
        ):
            for query in _build_fallback_music_queries(request_plan=request_plan)[
                : _fallback_query_batch_limit(request_plan.mode)
            ]:
                fallback_music_candidates = _deduplicate_candidates(
                    [
                        *fallback_music_candidates,
                        *_tag_search_candidates(
                            search_music_candidates(query=query, limit=per_query_limit),
                            requested_tags=tags,
                            search_query=query,
                            extra_tags=["fallback_search"],
                        ),
                    ],
                    limit=music_limit,
                )
                if (
                    len(preference_candidates)
                    + len(personalized_candidates)
                    + len(targeted_music_candidates)
                    + len(fallback_music_candidates)
                    >= music_limit
                ):
                    break
        timings["fallback_music_search"] = monotonic() - step_started_at

        step_started_at = monotonic()
        music_candidates = _prioritize_candidate_pool(
            [
                *targeted_music_candidates,
                *preference_candidates,
                *personalized_candidates,
                *fallback_music_candidates,
            ],
            avoid_candidate_ids=avoid_candidate_ids,
            recent_creators=recent_creators,
            limit=music_limit,
            preferred_title=request_plan.preferred_title,
            preferred_artist=request_plan.preferred_artist,
            strict_artist_only=request_plan.mode == "artist_focus",
            strict_title_only=request_plan.mode == "precise_song",
        )
        timings["music_prioritization"] = monotonic() - step_started_at

        step_started_at = monotonic()
        if (
            not music_candidates
            and not is_strict_targeting
            and request_plan.mode in {"general", "mood_mix"}
        ):
            broad_music_pool: list[CandidateItem] = []
            attempted_query_keys = {
                query.lower()
                for query in [
                    *query_plan[: _query_batch_limit(request_plan.mode)],
                    *_build_fallback_music_queries(request_plan=request_plan)[
                        : _fallback_query_batch_limit(request_plan.mode)
                    ],
                ]
            }
            broad_queries = [
                query
                for query in _build_broad_music_queries(
                    request_plan=request_plan,
                    memory=resolved_memory,
                )
                if query.lower() not in attempted_query_keys
            ]
            for query in broad_queries[:2]:
                broad_music_pool = _deduplicate_candidates(
                    [
                        *broad_music_pool,
                        *_tag_search_candidates(
                            search_music_candidates(query=query, limit=per_query_limit),
                            requested_tags=tags,
                            search_query=query,
                            extra_tags=["broad_fallback"],
                        ),
                    ],
                    limit=music_limit,
                )
                if broad_music_pool:
                    break

            if not broad_music_pool:
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
                strict_artist_only=request_plan.mode == "artist_focus",
                strict_title_only=request_plan.mode == "precise_song",
            )
        timings["broad_music_fallback"] = monotonic() - step_started_at

        podcast_candidates: list[CandidateItem] = []
        step_started_at = monotonic()
        if podcast_limit > 0:
            podcast_query = query_plan[0] if query_plan else None
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
        timings["podcast_candidates"] = monotonic() - step_started_at

        step_started_at = monotonic()
        candidate_items = _deduplicate_candidates(
            [*music_candidates, *podcast_candidates],
            limit=request.max_candidates,
        )
        timings["deduplicate"] = monotonic() - step_started_at

        warnings: list[str] = [*planner_warnings]
        if is_strict_targeting and not music_candidates:
            warnings.append(
                "No music candidates matched the requested song or artist; "
                "no unrelated fallback tracks were added."
            )
        elif has_targeting and not (
            preference_candidates or personalized_candidates or targeted_music_candidates
        ):
            warnings.append(
                "No personalized or targeted music candidates matched; used fallback results."
            )
        if not candidate_items:
            warnings.append("No candidate content is available; radio generation cannot continue.")

        timings["total"] = monotonic() - started_at
        if include_timings:
            return candidate_items, warnings, timings
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


def _can_use_local_request_plan(message: str) -> bool:
    text = message.strip().lower()
    if not text:
        return True
    auto_boot_markers = [
        "open clownfishstudio",
        "create a fresh hosted radio set",
        "start a small personal radio set",
        "generate a fresh station",
        "启动 clownfishstudio",
        "启动clownfishstudio",
        "此刻的电台",
    ]
    return any(marker in text for marker in auto_boot_markers)


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


def _per_query_limit(*, mode: str, music_limit: int) -> int:
    if mode == "precise_song":
        return max(3, min(5, music_limit))
    if mode == "artist_focus":
        return max(4, min(6, music_limit))
    return max(3, min(5, music_limit))


def _query_batch_limit(mode: str) -> int:
    if mode in {"precise_song", "artist_focus"}:
        return 2
    if mode == "mood_mix":
        return 3
    return 2


def _fallback_query_batch_limit(mode: str) -> int:
    return 0 if mode in {"precise_song", "artist_focus"} else 1


def _targeted_batch_goal(*, mode: str, music_limit: int) -> int:
    if mode == "precise_song":
        return 1
    if mode == "artist_focus":
        return min(4, music_limit)
    if mode == "mood_mix":
        return min(5, music_limit)
    return min(4, music_limit)


def _build_music_query_plan(request_plan: object) -> list[str]:
    search_queries = [
        sanitized_query
        for query in getattr(request_plan, "search_queries", [])
        if isinstance(query, str) and query.strip()
        if (sanitized_query := _sanitize_music_query(query))
    ]
    preferred_title = getattr(request_plan, "preferred_title", None)
    preferred_artist = getattr(request_plan, "preferred_artist", None)
    preferred_tags = [
        tag
        for tag in getattr(request_plan, "preferred_tags", [])
        if isinstance(tag, str) and tag.strip()
    ][:3]
    mode = getattr(request_plan, "mode", "general")

    if mode == "precise_song":
        queries = [
            _join_query_parts(preferred_title, preferred_artist),
            preferred_title,
            *search_queries[:2],
        ]
    elif mode == "artist_focus":
        queries = [
            preferred_artist,
            _join_query_parts(preferred_artist, preferred_tags[:1]),
            *search_queries[:2],
        ]
    else:
        queries = [
            *search_queries[:3],
            _join_query_parts(preferred_artist, preferred_tags[:1]),
            _join_query_parts(preferred_tags[:2]),
        ]

    return _unique_strings(query for value in queries if (query := _sanitize_music_query(value)))


def _build_fallback_music_queries(request_plan: object) -> list[str]:
    search_queries = [
        query
        for query in getattr(request_plan, "search_queries", [])
        if isinstance(query, str) and query.strip()
    ]
    preferred_tags = [
        tag
        for tag in getattr(request_plan, "preferred_tags", [])
        if isinstance(tag, str) and tag.strip()
    ][:3]
    queries: list[str | None] = [
        *search_queries[3:],
        _join_query_parts(preferred_tags),
    ]
    return _unique_strings(query for value in queries if (query := _sanitize_music_query(value)))


def _build_broad_music_queries(
    request_plan: object,
    memory: UserMusicMemory,
) -> list[str]:
    search_queries = [
        query
        for query in getattr(request_plan, "search_queries", [])
        if isinstance(query, str) and query.strip()
    ]
    preferred_tags = [
        tag
        for tag in getattr(request_plan, "preferred_tags", [])
        if isinstance(tag, str) and tag.strip()
    ][:3]
    queries: list[str | None] = [
        getattr(request_plan, "preferred_artist", None),
        getattr(request_plan, "preferred_title", None),
        _join_query_parts(preferred_tags[:2]),
        *memory.favorite_artists[:2],
        *memory.favorite_genres[:2],
        *search_queries,
    ]
    return _unique_strings(query for value in queries if (query := _sanitize_music_query(value)))


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
    strict_artist_only: bool = False,
    strict_title_only: bool = False,
) -> list[CandidateItem]:
    if limit <= 0:
        return []

    deduplicated = _deduplicate_candidates(candidates, limit=len(candidates))
    if strict_title_only and preferred_title:
        strict_matches = [
            candidate
            for candidate in deduplicated
            if _match_priority(candidate.title, preferred_title) >= 2
            and (not preferred_artist or _match_priority(candidate.creator, preferred_artist) >= 1)
        ]
        deduplicated = strict_matches
    elif strict_artist_only and preferred_artist:
        strict_matches = [
            candidate
            for candidate in deduplicated
            if _match_priority(candidate.creator, preferred_artist) >= 2
        ]
        deduplicated = strict_matches

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


def _filter_targeted_candidates(
    candidates: list[CandidateItem],
    preferred_title: str | None,
    preferred_artist: str | None,
    mode: str,
) -> list[CandidateItem]:
    if not candidates:
        return []

    if mode == "precise_song" and preferred_title:
        exact_title_matches = [
            candidate
            for candidate in candidates
            if _match_priority(candidate.title, preferred_title) >= 2
            and (not preferred_artist or _match_priority(candidate.creator, preferred_artist) >= 1)
        ]
        return exact_title_matches

    if mode == "artist_focus" and preferred_artist:
        artist_matches = [
            candidate
            for candidate in candidates
            if _match_priority(candidate.creator, preferred_artist) >= 2
        ]
        return artist_matches

    return candidates


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
        *[candidate for candidate in candidates if _is_recent_creator(candidate, recent_creators)],
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


def _sanitize_music_query(value: str | None) -> str | None:
    normalized = _normalize_query(value)
    if not normalized:
        return None

    normalized = re.sub(
        r"\b(play|listen to|search for|find|recommend|songs?|music|tracks?)\b",
        " ",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"(我想听|想听|播放|推荐|放一些|放点|来点|来一些|帮我找|搜一下|找一下|"
        r"歌曲|歌单|音乐|的歌)",
        " ",
        normalized,
    )
    normalized = re.sub(
        r"\b(companionship|unknown|weather unavailable|unavailable)\b",
        " ",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"\b(clownfishstudio|clownfish)\b|启动|打招呼|自我介绍|此刻的电台|电台",
        " ",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized if len(normalized) >= 2 else None


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
