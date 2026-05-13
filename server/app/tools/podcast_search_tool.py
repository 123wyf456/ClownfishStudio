from app.schemas import CandidateItem, ContentType
from app.tools.mock_data import read_mock_json


def search_podcast_candidates(
    query: str | None = None,
    tags: list[str] | None = None,
    limit: int = 10,
) -> list[CandidateItem]:
    data = read_mock_json("podcast_candidates.json")
    items = data["items"]

    if not isinstance(items, list):
        raise ValueError("podcast candidate mock data is malformed")

    candidates = [
        CandidateItem.model_validate(item)
        for item in items
        if isinstance(item, dict) and item.get("content_type") == ContentType.podcast.value
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
