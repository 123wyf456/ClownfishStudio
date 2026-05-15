import json

from app.schemas import (
    CandidateItem,
    ChatMessage,
    ContextSnapshot,
    RadioProgram,
    StationSession,
    UserMusicMemory,
)

SYSTEM_PROMPT = """
You are the ClownfishStudio radio agent.
You decide the radio program structure, narration, and candidate ordering.
Tools provide facts and playable candidates. You must not invent playable content.
Every music or podcast item must reference a provided candidate_id.
Create a hosted personal radio program, not a search result list.
When enough playable music candidates are available, the station should usually
contain around 7 to 9 playable items, unless the user clearly asked for a much
shorter set.
Candidates tagged user_preference, recent_favorite, liked_track, or playlist_seed
come from the user's real NetEase listening history or playlists. Treat them as
evidence of actual taste, not generic search results.
Candidates tagged personalized_recommendation, daily_recommend,
recommended_playlist_seed, favorite_artist_match, or favorite_genre_match come
from live NetEase recommendation surfaces. Use them to widen the station beyond
the exact same seed songs while staying close to the user's real taste.
When those preference-tagged candidates fit the current moment, use them as the
main anchors of the program. If the user asks for something close to their usual
taste, most music items should come from those preference-tagged candidates when
they are available. Use generic search-result tracks mainly for discovery or
contrast around those anchors.
Avoid repeating tracks or artists that appear in recent history unless there are
too few good alternatives.
If recent chat history is provided, treat the newest user message as the active
instruction and keep earlier turns as continuity. Reflect the change in the
program structure and opening narration.
The first item must be a warm opening narration that introduces Clownfish and
fits the moment in one short spoken sentence. On app startup, simply say hello
and introduce yourself; do not recap city, weather, date, candidate lists, or
why each track was chosen.
Add very short bridge narrations between tracks so the program feels hosted
rather than like a plain playlist. Avoid long explanations in narration.
For every playable item, write a concrete explanation based on context, user
memory, tags, and candidate metadata. Do not mention internal tool IDs in
user-facing narration, but do set candidate_id exactly for playable items.
Match the user's language. If the locale or free text suggests Chinese, prefer
natural spoken Simplified Chinese for titles, summaries, and narration.
Return a radio program draft with title, summary, and blocks. The server will
add program_id, context_snapshot, total_duration_minutes, and generated_at.
""".strip()

SHORT_TEXT_SYSTEM_PROMPT = """
You are the ClownfishStudio radio host.
Return only one JSON object with a single key named "text".
Write a short spoken reply, usually one or two sentences.
Keep it warm, direct, and natural.
Prefer one sentence. For Chinese, keep it under 30 characters when possible.
For English, keep it under 14 words when possible.
Do not mention internal IDs, schemas, or tool names.
Do not explain your reasoning.
For a greeting, lightly welcome the listener and set the tone.
For a chat reply, answer the user's latest message and keep the station moving.
""".strip()

CHAT_TURN_SYSTEM_PROMPT = """
You are the ClownfishStudio chat routing agent.
Return only one JSON object with keys "intent" and "reply_text".
Allowed intent values are chat_only, retune_program, song_request, config_help.
Use chat_only for normal conversation that does not require changing the station.
Use retune_program when the listener asks to change the mood, pacing, topic, or station direction.
Use song_request when the listener asks for a specific song, artist, genre, or music need.
Use config_help when the listener asks about API keys, settings, NetEase, Anthropic, TTS, or setup.
reply_text should be a short natural host response in the user's language.
reply_text must react to the user's actual words, not a stock acknowledgement,
recap, or explanation.
For Chinese, keep reply_text under 30 characters when possible.
For English, keep reply_text under 14 words when possible.
Do not mention city, weather, internal IDs, schemas, or tools unless the user asks.
""".strip()


def build_radio_prompt(
    context_snapshot: ContextSnapshot,
    memory: UserMusicMemory,
    history: list[dict[str, str]],
    candidate_items: list[CandidateItem],
    chat_history: list[ChatMessage] | None = None,
) -> str:
    preference_candidates = [
        candidate for candidate in candidate_items if _is_preference_candidate(candidate)
    ]
    candidate_lines = [_format_candidate(candidate) for candidate in candidate_items]
    preference_candidate_lines = [
        (
            f"- {candidate.candidate_id}: {candidate.title} by {candidate.creator}; "
            f"tags={candidate.tags}"
        )
        for candidate in preference_candidates
    ]

    return "\n".join(
        [
            SYSTEM_PROMPT,
            "",
            "Context:",
            json.dumps(
                {
                    "device_context": context_snapshot.device_context.model_dump(mode="json"),
                    "user_state": context_snapshot.user_state.model_dump(mode="json"),
                    "weather": context_snapshot.weather,
                },
                ensure_ascii=False,
            ),
            "",
            "User music memory:",
            json.dumps(
                {
                    "favorite_genres": memory.favorite_genres[:8],
                    "favorite_artists": memory.favorite_artists[:8],
                    "disliked_artists": memory.disliked_artists[:6],
                    "recent_candidate_ids": memory.recent_candidate_ids[:12],
                },
                ensure_ascii=False,
            ),
            "",
            "Recent history:",
            json.dumps(history[-12:], ensure_ascii=False),
            "",
            "Recent chat history:",
            _format_chat_history(chat_history or []),
            "",
            "Preference anchor candidates from the user's real NetEase taste:",
            "\n".join(preference_candidate_lines) if preference_candidate_lines else "None",
            "",
            "Candidate items:",
            "\n".join(candidate_lines),
        ]
    )


def build_station_greeting_prompt(
    request_context: ContextSnapshot,
    program: RadioProgram,
    chat_history: list[ChatMessage] | None = None,
) -> str:
    return "\n".join(
        [
            SHORT_TEXT_SYSTEM_PROMPT,
            "",
            "Mode:",
            "greeting",
            "",
            "Context snapshot:",
            request_context.model_dump_json(),
            "",
            "Program:",
            program.model_dump_json(),
            "",
            "Recent chat history:",
            _format_chat_history(chat_history or []),
            "",
            "Return a short greeting for the opening of this station.",
        ]
    )


def build_station_chat_reply_prompt(
    session: StationSession,
    message: str,
    chat_history: list[ChatMessage] | None = None,
) -> str:
    return "\n".join(
        [
            SHORT_TEXT_SYSTEM_PROMPT,
            "",
            "Mode:",
            "chat_reply",
            "",
            "Latest user message:",
            message,
            "",
            "Session:",
            session.model_dump_json(),
            "",
            "Recent chat history:",
            _format_chat_history(chat_history or []),
            "",
            "Return a short reply that reacts to the user's message and keeps the station aligned.",
        ]
    )


def build_chat_turn_prompt(
    session: StationSession,
    message: str,
    chat_history: list[ChatMessage] | None = None,
) -> str:
    current_tracks = [
        f"{item.title} - {item.creator}"
        for block in session.program.blocks
        for item in block.items
        if item.item_type != "narration"
    ][:6]
    context = {
        "station_title": session.program.title,
        "station_summary": session.program.summary,
        "current_tracks": current_tracks,
    }
    return "\n".join(
        [
            CHAT_TURN_SYSTEM_PROMPT,
            "",
            "Latest user message:",
            message,
            "",
            "Current station context:",
            str(context),
            "",
            "Recent chat history:",
            _format_chat_history(chat_history or []),
            "",
            "Return JSON now.",
        ]
    )


def _is_preference_candidate(candidate: CandidateItem) -> bool:
    preference_tags = {"user_preference", "recent_favorite", "liked_track", "playlist_seed"}
    return any(tag.lower() in preference_tags for tag in candidate.tags)


def _format_candidate(candidate: CandidateItem) -> str:
    public_tags = [
        tag
        for tag in candidate.tags
        if tag.lower() not in {"netease", "real_playback", "search_result", "query_match"}
    ][:6]
    tags = f"; tags={public_tags}" if public_tags else ""
    return (
        f"- {candidate.candidate_id}: {candidate.title} by {candidate.creator}; "
        f"type={candidate.content_type.value}; duration={candidate.duration_seconds}{tags}"
    )


def _format_chat_history(chat_history: list[ChatMessage]) -> str:
    if not chat_history:
        return "None"

    return "\n".join(f"- {message.role}: {message.text}" for message in chat_history[-6:])
