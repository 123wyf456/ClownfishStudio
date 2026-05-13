from app.schemas import UserMusicMemory
from app.tools.history_tool import get_recent_candidate_ids
from app.tools.mock_data import read_mock_json
from app.tools.netease_music_tool import get_netease_user_music_memory


def get_user_music_memory(user_id: str) -> UserMusicMemory:
    local_memory = _get_local_user_music_memory(user_id)
    netease_memory = get_netease_user_music_memory(user_id)
    merged_memory = (
        local_memory
        if netease_memory is None
        else _merge_user_memories(local_memory, netease_memory)
    )

    return merged_memory.model_copy(
        update={
            "recent_candidate_ids": _merge_unique(
                get_recent_candidate_ids(user_id=user_id, limit=20),
                merged_memory.recent_candidate_ids,
            )
        }
    )


def _get_local_user_music_memory(user_id: str) -> UserMusicMemory:
    data = read_mock_json("music_memory.json")
    users = data["users"]

    if not isinstance(users, list):
        raise ValueError("music memory mock data is malformed")

    for user in users:
        if isinstance(user, dict) and user.get("user_id") == user_id:
            return UserMusicMemory.model_validate(user)

    return UserMusicMemory(user_id=user_id)


def _merge_user_memories(
    local_memory: UserMusicMemory,
    netease_memory: UserMusicMemory,
) -> UserMusicMemory:
    return UserMusicMemory(
        user_id=local_memory.user_id,
        favorite_genres=_merge_unique(local_memory.favorite_genres, netease_memory.favorite_genres),
        favorite_artists=_merge_unique(
            local_memory.favorite_artists,
            netease_memory.favorite_artists,
        ),
        disliked_artists=_merge_unique(
            local_memory.disliked_artists,
            netease_memory.disliked_artists,
        ),
        recent_candidate_ids=_merge_unique(
            local_memory.recent_candidate_ids,
            netease_memory.recent_candidate_ids,
        ),
        updated_at=max(local_memory.updated_at, netease_memory.updated_at),
    )


def _merge_unique(first: list[str], second: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for values in (second, first):
        for value in values:
            normalized = value.strip()
            key = normalized.lower()
            if not normalized or key in seen:
                continue
            seen.add(key)
            merged.append(normalized)
    return merged
