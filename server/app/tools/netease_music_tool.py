from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from app.core.config import RUNTIME_ROOT, get_settings
from app.schemas import (
    CandidateItem,
    ContentType,
    MusicAccountStatus,
    MusicHealthResponse,
    MusicPreferenceStatus,
    UserMusicMemory,
)

PREFERENCE_CACHE_TTL_SECONDS = 15 * 60
NETEASE_RESPONSE_CACHE_TTL_SECONDS = 24 * 60 * 60
NETEASE_CACHE_DIR = RUNTIME_ROOT / "cache" / "netease"
NETEASE_UNCACHED_PATHS = {"/search", "/song/url/v1"}


class NeteaseMusicToolError(RuntimeError):
    pass


@dataclass(frozen=True)
class NeteaseSeedSong:
    song: dict[str, object]
    tags: tuple[str, ...]
    source: str


@dataclass(frozen=True)
class NeteasePreferenceSnapshot:
    netease_user_id: str
    favorite_artists: tuple[str, ...]
    favorite_genres: tuple[str, ...]
    seed_songs: tuple[NeteaseSeedSong, ...]


_PREFERENCE_CACHE: dict[str, tuple[float, NeteasePreferenceSnapshot]] = {}


def is_netease_music_enabled() -> bool:
    return bool(get_settings().netease_api_base_url)


def search_netease_music_candidates(
    query: str,
    limit: int = 10,
) -> list[CandidateItem]:
    settings = get_settings()
    if not settings.netease_api_base_url:
        return []

    normalized_query = query.strip()
    if not normalized_query:
        return []

    songs = _search_songs(
        base_url=settings.netease_api_base_url,
        cookie=settings.netease_cookie,
        query=normalized_query,
        limit=limit,
    )
    return _seed_songs_to_candidates(
        base_url=settings.netease_api_base_url,
        cookie=settings.netease_cookie,
        playback_level=settings.netease_playback_level,
        seed_songs=[
            NeteaseSeedSong(song=song, tags=("search_result",), source="search") for song in songs
        ],
        limit=limit,
    )


def get_netease_music_health() -> MusicHealthResponse:
    settings = get_settings()
    if not settings.netease_api_base_url:
        return MusicHealthResponse(
            provider="netease_cloud_music",
            base_url=None,
            search_ok=False,
            playback_ok=False,
            account=MusicAccountStatus(
                connected=False,
                anonymous=True,
                has_profile=False,
                detail="NETEASE_API_BASE_URL is not configured.",
            ),
            preference_status=MusicPreferenceStatus(
                detail=(
                    "NetEase preference signals are unavailable because the API base URL "
                    "is missing."
                )
            ),
        )

    try:
        account_payload = _get_json(
            base_url=settings.netease_api_base_url,
            path="/login/status",
            params={},
            cookie=settings.netease_cookie,
        )
        account = _parse_account_status(account_payload)
        preference_status = _probe_preference_status(
            base_url=settings.netease_api_base_url,
            cookie=settings.netease_cookie,
            account=account,
        )
    except NeteaseMusicToolError as exc:
        return MusicHealthResponse(
            provider="netease_cloud_music",
            base_url=settings.netease_api_base_url,
            search_ok=False,
            playback_ok=False,
            account=MusicAccountStatus(
                connected=False,
                anonymous=True,
                has_profile=False,
                detail=str(exc),
            ),
            preference_status=MusicPreferenceStatus(
                detail=f"NetEase preference probe failed: {exc}"
            ),
        )

    search_ok = False
    playback_ok = False
    try:
        songs = _search_songs(
            base_url=settings.netease_api_base_url,
            cookie=settings.netease_cookie,
            query="Jay Chou",
            limit=1,
        )
        search_ok = bool(songs)
        if songs:
            first_song_id = songs[0].get("id")
            if isinstance(first_song_id, int):
                playback_ok = (
                    _get_playback_url(
                        base_url=settings.netease_api_base_url,
                        cookie=settings.netease_cookie,
                        song_id=first_song_id,
                        playback_level=settings.netease_playback_level,
                    )
                    is not None
                )
    except NeteaseMusicToolError:
        search_ok = False
        playback_ok = False

    return MusicHealthResponse(
        provider="netease_cloud_music",
        base_url=settings.netease_api_base_url,
        search_ok=search_ok,
        playback_ok=playback_ok,
        account=account,
        preference_status=preference_status,
    )


def get_netease_user_music_memory(app_user_id: str) -> UserMusicMemory | None:
    settings = get_settings()
    if not settings.netease_api_base_url:
        return None

    snapshot = _get_preference_snapshot(
        base_url=settings.netease_api_base_url,
        cookie=settings.netease_cookie,
    )
    if snapshot is None:
        return None

    return UserMusicMemory(
        user_id=app_user_id,
        favorite_genres=list(snapshot.favorite_genres),
        favorite_artists=list(snapshot.favorite_artists),
        disliked_artists=[],
        recent_candidate_ids=[],
    )


def get_netease_preference_candidates(limit: int = 8) -> list[CandidateItem]:
    settings = get_settings()
    if not settings.netease_api_base_url:
        return []

    snapshot = _get_preference_snapshot(
        base_url=settings.netease_api_base_url,
        cookie=settings.netease_cookie,
    )
    if snapshot is None:
        return []

    return _seed_songs_to_candidates(
        base_url=settings.netease_api_base_url,
        cookie=settings.netease_cookie,
        playback_level=settings.netease_playback_level,
        seed_songs=[
            NeteaseSeedSong(
                song=seed.song,
                tags=tuple(_merge_unique_strings(["user_preference", *seed.tags])),
                source=seed.source,
            )
            for seed in snapshot.seed_songs
        ],
        limit=limit,
        metadata_label="preference_source",
    )


def get_netease_personalized_candidates(limit: int = 12) -> list[CandidateItem]:
    settings = get_settings()
    if not settings.netease_api_base_url:
        return []

    snapshot = _get_preference_snapshot(
        base_url=settings.netease_api_base_url,
        cookie=settings.netease_cookie,
    )
    if snapshot is None:
        return []

    seed_songs = [
        *_build_daily_recommendation_seed_songs(
            base_url=settings.netease_api_base_url,
            cookie=settings.netease_cookie,
        ),
        *_build_personalized_new_song_seeds(
            base_url=settings.netease_api_base_url,
            cookie=settings.netease_cookie,
        ),
        *_build_recommended_playlist_seed_songs(
            base_url=settings.netease_api_base_url,
            cookie=settings.netease_cookie,
        ),
    ]

    favorite_artist_keys = {artist.lower() for artist in snapshot.favorite_artists}
    favorite_genre_keys = {genre.lower() for genre in snapshot.favorite_genres}
    personalized_seeds: list[NeteaseSeedSong] = []
    for seed in seed_songs:
        tags = list(seed.tags)
        creators = {artist.lower() for artist in _read_artists(seed.song)}
        if creators.intersection(favorite_artist_keys):
            tags.append("favorite_artist_match")
        if any(tag.lower() in favorite_genre_keys for tag in tags):
            tags.append("favorite_genre_match")
        personalized_seeds.append(
            NeteaseSeedSong(
                song=seed.song,
                tags=tuple(_merge_unique_strings(["personalized_recommendation", *tags])),
                source=seed.source,
            )
        )

    return _seed_songs_to_candidates(
        base_url=settings.netease_api_base_url,
        cookie=settings.netease_cookie,
        playback_level=settings.netease_playback_level,
        seed_songs=personalized_seeds,
        limit=limit,
        metadata_label="personalized_source",
    )


def _probe_preference_status(
    base_url: str,
    cookie: str | None,
    account: MusicAccountStatus,
) -> MusicPreferenceStatus:
    playlist_names: list[str] = []
    playlists: list[dict[str, object]] = []
    liked_playlist_track_count = 0
    has_liked_playlist = False
    history_songs: list[dict[str, object]] = []
    daily_recommendations: list[NeteaseSeedSong] = []
    personalized_new_songs: list[NeteaseSeedSong] = []
    recommended_playlists: list[NeteaseSeedSong] = []

    if account.user_id:
        playlists = _safe_get_user_playlists(
            base_url=base_url,
            cookie=cookie,
            netease_user_id=account.user_id,
        )
        playlist_names = [
            name
            for playlist in playlists[:3]
            if isinstance((name := playlist.get("name")), str) and name.strip()
        ]
        history_songs = _safe_get_record_songs(
            base_url=base_url,
            cookie=cookie,
            netease_user_id=account.user_id,
        )
        liked_playlist = _find_liked_playlist(playlists, account.user_id)
        if liked_playlist is not None:
            has_liked_playlist = True
            liked_playlist_track_count = int(liked_playlist.get("trackCount") or 0)

    try:
        daily_recommendations = _build_daily_recommendation_seed_songs(
            base_url=base_url,
            cookie=cookie,
        )
    except NeteaseMusicToolError:
        daily_recommendations = []

    try:
        personalized_new_songs = _build_personalized_new_song_seeds(
            base_url=base_url,
            cookie=cookie,
        )
    except NeteaseMusicToolError:
        personalized_new_songs = []

    try:
        recommended_playlists = _build_recommended_playlist_seed_songs(
            base_url=base_url,
            cookie=cookie,
        )
    except NeteaseMusicToolError:
        recommended_playlists = []

    has_profile = account.has_profile or bool(account.nickname)
    detail_parts: list[str] = []
    if history_songs:
        detail_parts.append(f"history:{len(history_songs)}")
    if playlists:
        detail_parts.append(f"playlists:{len(playlists)}")
    if daily_recommendations:
        detail_parts.append(f"daily:{len(daily_recommendations)}")
    if personalized_new_songs:
        detail_parts.append(f"new:{len(personalized_new_songs)}")
    if recommended_playlists:
        detail_parts.append(f"recommended_playlists:{len(recommended_playlists)}")
    if not detail_parts:
        detail_parts.append("no personalized endpoints returned usable data")

    return MusicPreferenceStatus(
        can_read_profile=has_profile,
        can_read_playlists=bool(playlists),
        can_read_liked_playlist=has_liked_playlist,
        can_read_liked_songs=liked_playlist_track_count > 0,
        can_read_history=bool(history_songs),
        can_read_daily_recommendations=bool(daily_recommendations),
        can_read_personalized_new_songs=bool(personalized_new_songs),
        can_read_recommended_playlists=bool(recommended_playlists),
        playlist_count=len(playlists),
        liked_playlist_track_count=liked_playlist_track_count,
        history_count=len(history_songs),
        daily_recommendation_count=len(daily_recommendations),
        personalized_new_song_count=len(personalized_new_songs),
        recommended_playlist_count=len(recommended_playlists),
        sample_playlist_names=playlist_names,
        detail=", ".join(detail_parts),
    )


def _get_preference_snapshot(
    base_url: str,
    cookie: str | None,
) -> NeteasePreferenceSnapshot | None:
    cache_key = f"{base_url}|{cookie or ''}"
    cached = _PREFERENCE_CACHE.get(cache_key)
    if cached is not None and monotonic() - cached[0] < PREFERENCE_CACHE_TTL_SECONDS:
        return cached[1]

    account_payload = _get_json(
        base_url=base_url,
        path="/login/status",
        params={},
        cookie=cookie,
    )
    account = _parse_account_status(account_payload)
    if not account.connected or not account.user_id:
        return None

    netease_user_id = account.user_id
    record_songs = _safe_get_record_songs(
        base_url=base_url,
        cookie=cookie,
        netease_user_id=netease_user_id,
    )
    playlists = _safe_get_user_playlists(
        base_url=base_url,
        cookie=cookie,
        netease_user_id=netease_user_id,
    )
    liked_playlist = _find_liked_playlist(playlists, netease_user_id)
    owned_playlists = _find_owned_seed_playlists(playlists, netease_user_id)

    liked_songs = (
        _safe_get_playlist_songs(
            base_url=base_url,
            cookie=cookie,
            playlist_id=liked_playlist["id"],
            limit=8,
        )
        if liked_playlist is not None
        else []
    )

    playlist_seed_songs: list[NeteaseSeedSong] = []
    for playlist in owned_playlists:
        playlist_id = playlist.get("id")
        if not isinstance(playlist_id, int):
            continue
        playlist_tags = _extract_playlist_genres(playlist)
        songs = _safe_get_playlist_songs(
            base_url=base_url,
            cookie=cookie,
            playlist_id=playlist_id,
            limit=5,
        )
        for song in songs:
            playlist_seed_songs.append(
                NeteaseSeedSong(
                    song=song,
                    tags=tuple(_merge_unique_strings([*playlist_tags, "playlist_seed"])),
                    source=f"playlist:{playlist_id}",
                )
            )

    favorite_artists = _build_favorite_artists(
        record_songs=record_songs,
        liked_songs=liked_songs,
        playlist_seed_songs=playlist_seed_songs,
        personalized_seed_songs=[
            *_build_daily_recommendation_seed_songs(base_url=base_url, cookie=cookie),
            *_build_personalized_new_song_seeds(base_url=base_url, cookie=cookie),
        ],
    )
    favorite_genres = _build_favorite_genres(playlists, netease_user_id)
    seed_songs = _build_seed_songs(
        record_songs=record_songs,
        liked_songs=liked_songs,
        playlist_seed_songs=playlist_seed_songs,
        personalized_seed_songs=[
            *_build_daily_recommendation_seed_songs(base_url=base_url, cookie=cookie),
            *_build_personalized_new_song_seeds(base_url=base_url, cookie=cookie),
            *_build_recommended_playlist_seed_songs(base_url=base_url, cookie=cookie),
        ],
    )

    snapshot = NeteasePreferenceSnapshot(
        netease_user_id=netease_user_id,
        favorite_artists=tuple(favorite_artists),
        favorite_genres=tuple(favorite_genres),
        seed_songs=tuple(seed_songs),
    )
    _PREFERENCE_CACHE[cache_key] = (monotonic(), snapshot)
    return snapshot


def _get_record_songs(
    base_url: str,
    cookie: str | None,
    netease_user_id: str,
) -> list[dict[str, object]]:
    preferred_payload = _get_json(
        base_url=base_url,
        path="/user/record",
        params={"uid": netease_user_id, "type": 1},
        cookie=cookie,
    )
    songs = _extract_record_songs(preferred_payload)
    if songs:
        return songs

    fallback_payload = _get_json(
        base_url=base_url,
        path="/user/record",
        params={"uid": netease_user_id, "type": 0},
        cookie=cookie,
    )
    return _extract_record_songs(fallback_payload)


def _safe_get_record_songs(
    base_url: str,
    cookie: str | None,
    netease_user_id: str,
) -> list[dict[str, object]]:
    try:
        return _get_record_songs(
            base_url=base_url,
            cookie=cookie,
            netease_user_id=netease_user_id,
        )
    except NeteaseMusicToolError:
        return []


def _get_user_playlists(
    base_url: str,
    cookie: str | None,
    netease_user_id: str,
) -> list[dict[str, object]]:
    payload = _get_json(
        base_url=base_url,
        path="/user/playlist",
        params={"uid": netease_user_id},
        cookie=cookie,
    )
    playlists = payload.get("playlist")
    if not isinstance(playlists, list):
        return []

    return [item for item in playlists if isinstance(item, dict)]


def _safe_get_user_playlists(
    base_url: str,
    cookie: str | None,
    netease_user_id: str,
) -> list[dict[str, object]]:
    try:
        return _get_user_playlists(
            base_url=base_url,
            cookie=cookie,
            netease_user_id=netease_user_id,
        )
    except NeteaseMusicToolError:
        return []


def _get_playlist_songs(
    base_url: str,
    cookie: str | None,
    playlist_id: int,
    limit: int,
) -> list[dict[str, object]]:
    payload = _get_json(
        base_url=base_url,
        path="/playlist/track/all",
        params={"id": playlist_id, "limit": limit},
        cookie=cookie,
    )
    songs = payload.get("songs")
    return [item for item in songs if isinstance(item, dict)] if isinstance(songs, list) else []


def _safe_get_playlist_songs(
    base_url: str,
    cookie: str | None,
    playlist_id: int,
    limit: int,
) -> list[dict[str, object]]:
    try:
        return _get_playlist_songs(
            base_url=base_url,
            cookie=cookie,
            playlist_id=playlist_id,
            limit=limit,
        )
    except NeteaseMusicToolError:
        return []


def _extract_record_songs(payload: dict[str, object]) -> list[dict[str, object]]:
    container = payload.get("weekData") or payload.get("allData")
    if not isinstance(container, list):
        return []

    songs: list[dict[str, object]] = []
    for entry in container:
        if not isinstance(entry, dict):
            continue
        song = entry.get("song")
        if isinstance(song, dict):
            songs.append(song)
    return songs


def _find_liked_playlist(
    playlists: list[dict[str, object]],
    netease_user_id: str,
) -> dict[str, object] | None:
    for playlist in playlists:
        playlist_user_id = playlist.get("userId")
        special_type = playlist.get("specialType")
        if str(playlist_user_id) != netease_user_id:
            continue
        if special_type == 5:
            return playlist
    return None


def _find_owned_seed_playlists(
    playlists: list[dict[str, object]],
    netease_user_id: str,
) -> list[dict[str, object]]:
    owned_playlists = [
        playlist
        for playlist in playlists
        if str(playlist.get("userId")) == netease_user_id
        and playlist.get("specialType") == 0
        and isinstance(playlist.get("trackCount"), int)
        and int(playlist["trackCount"]) > 0
    ]
    owned_playlists.sort(
        key=lambda playlist: int(playlist.get("trackUpdateTime") or 0),
        reverse=True,
    )
    return owned_playlists[:2]


def _build_favorite_artists(
    record_songs: list[dict[str, object]],
    liked_songs: list[dict[str, object]],
    playlist_seed_songs: list[NeteaseSeedSong],
    personalized_seed_songs: list[NeteaseSeedSong],
) -> list[str]:
    counter: Counter[str] = Counter()
    _add_artist_counts(counter, record_songs, weight=3)
    _add_artist_counts(counter, liked_songs, weight=2)
    _add_artist_counts(
        counter,
        [seed.song for seed in playlist_seed_songs],
        weight=1,
    )
    _add_artist_counts(
        counter,
        [seed.song for seed in personalized_seed_songs],
        weight=1,
    )
    return [artist for artist, _ in counter.most_common(12)]


def _build_favorite_genres(
    playlists: list[dict[str, object]],
    netease_user_id: str,
) -> list[str]:
    counter: Counter[str] = Counter()

    for playlist in playlists:
        weight = 1
        if str(playlist.get("userId")) == netease_user_id:
            weight += 2
        if playlist.get("specialType") == 5:
            weight += 2
        for genre in _extract_playlist_genres(playlist):
            counter[genre] += weight

    return [genre for genre, _ in counter.most_common(8)]


def _build_seed_songs(
    record_songs: list[dict[str, object]],
    liked_songs: list[dict[str, object]],
    playlist_seed_songs: list[NeteaseSeedSong],
    personalized_seed_songs: list[NeteaseSeedSong],
) -> list[NeteaseSeedSong]:
    seeds: list[NeteaseSeedSong] = []

    for song in _pick_diverse_songs(record_songs, limit=8):
        seeds.append(
            NeteaseSeedSong(
                song=song,
                tags=("recent_favorite",),
                source="listening_record",
            )
        )

    for song in _pick_diverse_songs(liked_songs, limit=8):
        seeds.append(
            NeteaseSeedSong(
                song=song,
                tags=("liked_track",),
                source="liked_playlist",
            )
        )

    seeds.extend(playlist_seed_songs)
    seeds.extend(personalized_seed_songs)

    deduplicated: list[NeteaseSeedSong] = []
    seen_song_ids: set[int] = set()
    for seed in seeds:
        song_id = seed.song.get("id")
        if not isinstance(song_id, int) or song_id in seen_song_ids:
            continue
        seen_song_ids.add(song_id)
        deduplicated.append(seed)

    return deduplicated


def _build_daily_recommendation_seed_songs(
    base_url: str,
    cookie: str | None,
) -> list[NeteaseSeedSong]:
    payload = _get_json(
        base_url=base_url,
        path="/recommend/songs",
        params={},
        cookie=cookie,
    )
    data = payload.get("data")
    if not isinstance(data, dict):
        return []

    songs = data.get("dailySongs")
    if not isinstance(songs, list):
        return []

    return [
        NeteaseSeedSong(song=song, tags=("daily_recommend",), source="daily_recommend")
        for song in _pick_diverse_songs(
            [song for song in songs if isinstance(song, dict)],
            limit=8,
        )
    ]


def _build_personalized_new_song_seeds(
    base_url: str,
    cookie: str | None,
) -> list[NeteaseSeedSong]:
    payload = _get_json(
        base_url=base_url,
        path="/personalized/newsong",
        params={"limit": 8},
        cookie=cookie,
    )
    result = payload.get("result")
    if not isinstance(result, list):
        return []

    seeds: list[NeteaseSeedSong] = []
    for item in result:
        if not isinstance(item, dict):
            continue
        song = item.get("song")
        if not isinstance(song, dict):
            continue
        seeds.append(
            NeteaseSeedSong(
                song=song,
                tags=("new_discovery",),
                source="personalized_new_song",
            )
        )

    return seeds


def _build_recommended_playlist_seed_songs(
    base_url: str,
    cookie: str | None,
) -> list[NeteaseSeedSong]:
    payload = _get_json(
        base_url=base_url,
        path="/recommend/resource",
        params={},
        cookie=cookie,
    )
    playlists = payload.get("recommend")
    if not isinstance(playlists, list):
        return []

    seed_songs: list[NeteaseSeedSong] = []
    for playlist in playlists[:3]:
        if not isinstance(playlist, dict):
            continue
        playlist_id = playlist.get("id")
        if not isinstance(playlist_id, int):
            continue
        playlist_tags = _extract_playlist_genres(playlist)
        songs = _get_playlist_songs(
            base_url=base_url,
            cookie=cookie,
            playlist_id=playlist_id,
            limit=3,
        )
        for song in songs:
            seed_songs.append(
                NeteaseSeedSong(
                    song=song,
                    tags=tuple(
                        _merge_unique_strings([*playlist_tags, "recommended_playlist_seed"])
                    ),
                    source=f"recommended_playlist:{playlist_id}",
                )
            )

    return seed_songs


def _pick_diverse_songs(
    songs: list[dict[str, object]],
    limit: int,
) -> list[dict[str, object]]:
    if len(songs) <= limit:
        return songs

    selected: list[dict[str, object]] = []
    seen_song_ids: set[int] = set()
    max_window = min(len(songs), limit * 3)
    step = max_window / limit

    for index in range(limit):
        song = songs[min(int(index * step), max_window - 1)]
        song_id = song.get("id")
        if isinstance(song_id, int) and song_id not in seen_song_ids:
            seen_song_ids.add(song_id)
            selected.append(song)

    for song in songs:
        if len(selected) >= limit:
            break
        song_id = song.get("id")
        if not isinstance(song_id, int) or song_id in seen_song_ids:
            continue
        seen_song_ids.add(song_id)
        selected.append(song)

    return selected


def _add_artist_counts(
    counter: Counter[str],
    songs: list[dict[str, object]],
    weight: int,
) -> None:
    for song in songs:
        for artist in _read_artists(song):
            normalized = artist.strip()
            if normalized:
                counter[normalized] += weight


def _extract_playlist_genres(playlist: dict[str, object]) -> list[str]:
    tags = playlist.get("tags")
    raw_labels: list[str] = []
    if isinstance(tags, list):
        raw_labels.extend(tag for tag in tags if isinstance(tag, str))

    category = playlist.get("category")
    if isinstance(category, str) and category.strip():
        raw_labels.append(category)

    high_quality_tag = playlist.get("highQualityTag")
    if isinstance(high_quality_tag, str) and high_quality_tag.strip():
        raw_labels.append(high_quality_tag)
    elif isinstance(high_quality_tag, dict):
        tag_name = high_quality_tag.get("name")
        if isinstance(tag_name, str) and tag_name.strip():
            raw_labels.append(tag_name)

    preference_tags: list[str] = []
    for label in raw_labels:
        preference_tags.extend(_split_preference_label(label))

    return _merge_unique_strings(preference_tags)


def _split_preference_label(label: str) -> list[str]:
    normalized = label.strip()
    if not normalized:
        return []

    normalized = normalized.replace(" / ", "/").replace(" | ", "|").replace("，", ",")
    parts = [
        part.strip().lower()
        for part in re.split(r"\s*(?:/|,|\||\s+\&\s+)\s*", normalized)
        if part.strip()
    ]
    if not parts:
        return []

    return _merge_unique_strings([*parts, normalized.lower()])


def _search_songs(
    base_url: str,
    cookie: str | None,
    query: str,
    limit: int,
) -> list[dict[str, object]]:
    payload = _get_json(
        base_url=base_url,
        path="/search",
        params={"keywords": query, "limit": limit, "type": 1},
        cookie=cookie,
    )
    result = payload.get("result")
    if not isinstance(result, dict):
        return []

    songs = result.get("songs")
    return [song for song in songs if isinstance(song, dict)] if isinstance(songs, list) else []


def _song_to_candidate(
    base_url: str,
    cookie: str | None,
    playback_level: str,
    song: dict[str, object],
    playback_url: str | None = None,
) -> CandidateItem | None:
    song_id = song.get("id")
    if not isinstance(song_id, int):
        return None

    title = song.get("name")
    if not isinstance(title, str) or not title:
        return None

    creators = _read_artists(song)
    playback_url = playback_url or _get_playback_url(
        base_url=base_url,
        cookie=cookie,
        song_id=song_id,
        playback_level=playback_level,
    )
    if playback_url is None:
        return None

    duration_ms = song.get("duration") or song.get("dt")
    duration_seconds = int(duration_ms / 1000) if isinstance(duration_ms, int) else None

    return CandidateItem(
        candidate_id=f"netease-{song_id}",
        content_type=ContentType.music,
        title=title,
        creator=", ".join(creators) if creators else "NetEase Cloud Music",
        duration_seconds=duration_seconds,
        playback_url=playback_url,
        tags=["netease", "real_playback"],
        source="netease_cloud_music",
        metadata={
            "netease_song_id": song_id,
            "playback_level": playback_level,
        },
    )


def _seed_songs_to_candidates(
    base_url: str,
    cookie: str | None,
    playback_level: str,
    seed_songs: list[NeteaseSeedSong],
    limit: int,
    metadata_label: str | None = None,
) -> list[CandidateItem]:
    deduplicated_seeds: list[NeteaseSeedSong] = []
    seen_song_ids: set[int] = set()
    for seed in seed_songs:
        song_id = seed.song.get("id")
        if not isinstance(song_id, int) or song_id in seen_song_ids:
            continue
        seen_song_ids.add(song_id)
        deduplicated_seeds.append(seed)

    playback_urls = _get_playback_urls(
        base_url=base_url,
        cookie=cookie,
        song_ids=[
            song_id
            for seed in deduplicated_seeds
            if isinstance((song_id := seed.song.get("id")), int)
        ],
        playback_level=playback_level,
    )

    candidates: list[CandidateItem] = []
    for seed in deduplicated_seeds:
        song_id = seed.song.get("id")
        if not isinstance(song_id, int):
            continue
        candidate = _song_to_candidate(
            base_url=base_url,
            cookie=cookie,
            playback_level=playback_level,
            song=seed.song,
            playback_url=playback_urls.get(song_id),
        )
        if candidate is None:
            continue

        metadata = dict(candidate.metadata)
        if metadata_label:
            metadata[metadata_label] = seed.source
        candidates.append(
            candidate.model_copy(
                update={
                    "tags": _merge_unique_strings([*candidate.tags, *seed.tags]),
                    "metadata": metadata,
                }
            )
        )
        if len(candidates) >= limit:
            break

    return candidates


def _read_artists(song: dict[str, object]) -> list[str]:
    artists = song.get("artists") or song.get("ar")
    if not isinstance(artists, list):
        return []

    names: list[str] = []
    for artist in artists:
        if isinstance(artist, dict) and isinstance(artist.get("name"), str):
            names.append(artist["name"])

    return names


def _get_playback_url(
    base_url: str,
    cookie: str | None,
    song_id: int,
    playback_level: str,
) -> str | None:
    return _get_playback_urls(
        base_url=base_url,
        cookie=cookie,
        song_ids=[song_id],
        playback_level=playback_level,
    ).get(song_id)


def _get_playback_urls(
    base_url: str,
    cookie: str | None,
    song_ids: list[int],
    playback_level: str,
) -> dict[int, str]:
    if not song_ids:
        return {}

    payload = _get_json(
        base_url=base_url,
        path="/song/url/v1",
        params={"id": ",".join(str(song_id) for song_id in song_ids), "level": playback_level},
        cookie=cookie,
    )
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        return {}

    playback_urls: dict[int, str] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        song_id = item.get("id")
        url = item.get("url")
        if (
            isinstance(song_id, int)
            and isinstance(url, str)
            and url.startswith(("http://", "https://"))
        ):
            playback_urls[song_id] = url

    return playback_urls


def _get_json(
    base_url: str,
    path: str,
    params: dict[str, int | str],
    cookie: str | None,
) -> dict[str, object]:
    cache_key = _build_response_cache_key(
        base_url=base_url,
        path=path,
        params=params,
        cookie=cookie,
    )
    use_cache = path not in NETEASE_UNCACHED_PATHS
    if use_cache:
        cached_payload = _read_cached_json_response(cache_key)
        if cached_payload is not None:
            return cached_payload

    headers = {"Accept": "application/json"}
    if cookie:
        headers["Cookie"] = cookie

    last_network_error: Exception | None = None
    for candidate_base_url in _candidate_base_urls(base_url):
        url = f"{candidate_base_url.rstrip('/')}{path}?{urlencode(params)}"
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise NeteaseMusicToolError(f"NetEase API failed: {exc.code} {detail}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_network_error = exc
            continue

        if not isinstance(payload, dict):
            raise NeteaseMusicToolError("NetEase API returned non-object JSON")

        if use_cache:
            _write_cached_json_response(cache_key, payload)
        return payload

    raise NeteaseMusicToolError(f"NetEase API failed: {last_network_error}") from last_network_error


def _build_response_cache_key(
    base_url: str,
    path: str,
    params: dict[str, int | str],
    cookie: str | None,
) -> str:
    normalized_params = urlencode(sorted(params.items()))
    raw_key = "|".join(
        [
            base_url.rstrip("/"),
            path,
            normalized_params,
            cookie or "",
        ]
    )
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _read_cached_json_response(cache_key: str) -> dict[str, object] | None:
    cache_path = _response_cache_path(cache_key)
    if not cache_path.exists():
        return None

    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    cached_at = payload.get("cached_at")
    data = payload.get("data")
    if not isinstance(cached_at, (int, float)) or not isinstance(data, dict):
        return None

    if time() - float(cached_at) > NETEASE_RESPONSE_CACHE_TTL_SECONDS:
        return None

    return data


def _write_cached_json_response(cache_key: str, data: dict[str, object]) -> None:
    cache_path = _response_cache_path(cache_key)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = cache_path.with_suffix(".tmp")
        payload = {"cached_at": time(), "data": data}
        temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(cache_path)
    except OSError:
        return


def _response_cache_path(cache_key: str) -> Path:
    return NETEASE_CACHE_DIR / f"{cache_key}.json"


def _candidate_base_urls(base_url: str) -> list[str]:
    candidates = [base_url]
    parsed = urlparse(base_url)
    if parsed.hostname == "127.0.0.1":
        localhost_netloc = parsed.netloc.replace("127.0.0.1", "localhost")
        localhost_url = urlunparse(parsed._replace(netloc=localhost_netloc))
        candidates.append(localhost_url)
    return _merge_unique_strings(candidates)


def _parse_account_status(payload: dict[str, object]) -> MusicAccountStatus:
    data = payload.get("data")
    container = data if isinstance(data, dict) else payload
    account = container.get("account")
    profile = container.get("profile")

    if not isinstance(account, dict):
        return MusicAccountStatus(
            connected=False,
            anonymous=True,
            has_profile=False,
            detail="NetEase account payload is missing account data.",
        )

    user_id = account.get("id")
    username = account.get("userName")
    anonymous = bool(account.get("anonimousUser"))

    nickname = None
    if isinstance(profile, dict):
        raw_nickname = profile.get("nickname")
        if isinstance(raw_nickname, str) and raw_nickname.strip():
            nickname = raw_nickname.strip()
        profile_user_id = profile.get("userId")
        if profile_user_id is not None:
            user_id = profile_user_id

    detail_fragments: list[str] = []
    if anonymous:
        detail_fragments.append("Cookie session is currently anonymous.")
    if not nickname and not isinstance(profile, dict):
        detail_fragments.append("Profile data is unavailable.")

    return MusicAccountStatus(
        connected=True,
        anonymous=anonymous,
        user_id=str(user_id) if user_id is not None else None,
        nickname=nickname or (username if isinstance(username, str) else None),
        has_profile=isinstance(profile, dict),
        detail=" ".join(detail_fragments),
    )


def _merge_unique_strings(values: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        merged.append(normalized)
    return merged
