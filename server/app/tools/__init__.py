"""Tool integrations for facts, candidates, and mock persistence."""

from app.tools.feedback_tool import (
    build_memory_update_hint,
    list_feedback_events,
    list_memory_update_hints,
    save_feedback,
    save_memory_update_hint,
)
from app.tools.history_tool import (
    get_recent_candidate_ids,
    get_recent_history,
    save_history_event,
    save_program_history,
)
from app.tools.memory_tool import get_user_music_memory
from app.tools.music_search_tool import search_music_candidates
from app.tools.netease_music_tool import (
    get_netease_music_health,
    get_netease_personalized_candidates,
    get_netease_preference_candidates,
)
from app.tools.podcast_search_tool import search_podcast_candidates
from app.tools.program_tool import get_program, list_programs, save_program
from app.tools.weather_tool import get_weather

__all__ = [
    "build_memory_update_hint",
    "get_program",
    "get_netease_music_health",
    "get_netease_personalized_candidates",
    "get_netease_preference_candidates",
    "get_recent_candidate_ids",
    "get_recent_history",
    "get_user_music_memory",
    "get_weather",
    "list_feedback_events",
    "list_memory_update_hints",
    "list_programs",
    "save_feedback",
    "save_history_event",
    "save_memory_update_hint",
    "save_program",
    "save_program_history",
    "search_music_candidates",
    "search_podcast_candidates",
]
