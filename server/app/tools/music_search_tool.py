import logging

from app.schemas import CandidateItem, ContentType
from app.tools.mock_data import read_mock_json
from app.tools.netease_music_tool import (
    NeteaseMusicToolError,
    is_netease_music_enabled,
    search_netease_music_candidates,
)

LOGGER = logging.getLogger(__name__)


def search_music_candidates(
    query: str | None = None,
    tags: list[str] | None = None,
    limit: int = 10,
) -> list[CandidateItem]:
    if is_netease_music_enabled():
        netease_query = _netease_search_query(query=query, tags=tags)
        if netease_query:
            LOGGER.info(
                "netease_music_search query=%s limit=%s",
                netease_query,
                limit,
            )
            try:
                candidates = search_netease_music_candidates(query=netease_query, limit=limit)
            except NeteaseMusicToolError as exc:
                LOGGER.warning(
                    "netease_music_search_failed query=%s error=%s",
                    netease_query,
                    exc,
                )
                candidates = []
        else:
            candidates = []

        if candidates:
            return candidates

    data = read_mock_json("music_candidates.json")
    items = data["items"]

    if not isinstance(items, list):
        raise ValueError("music candidate mock data is malformed")

    candidates = [
        CandidateItem.model_validate(item)
        for item in items
        if isinstance(item, dict) and item.get("content_type") == ContentType.music.value
    ]
    return _filter_candidates(candidates=candidates, query=query, tags=tags, limit=limit)


def _filter_candidates(
    candidates: list[CandidateItem],
    query: str | None,
    tags: list[str] | None,
    limit: int,
) -> list[CandidateItem]:
    normalized_query = query.strip().lower() if query else None
    normalized_tags = {tag.lower() for tag in tags or []}

    filtered: list[CandidateItem] = []
    for candidate in candidates:
        if normalized_query and normalized_query not in _candidate_search_text(candidate):
            continue

        candidate_tags = {tag.lower() for tag in candidate.tags}
        if normalized_tags and not normalized_tags.intersection(candidate_tags):
            continue

        filtered.append(candidate)

    return filtered[:limit]


def _candidate_search_text(candidate: CandidateItem) -> str:
    return " ".join([candidate.title, candidate.creator, *candidate.tags]).lower()


def _netease_search_query(query: str | None, tags: list[str] | None) -> str | None:
    if query and query.strip():
        return query.strip()

    ignored_tags = {"companionship", "unknown", "weather unavailable", "unavailable"}
    usable_tags = [
        tag.strip()
        for tag in tags or []
        if tag.strip() and tag.strip().lower() not in ignored_tags
    ]
    joined = " ".join(usable_tags[:2]).strip()
    return joined or None
