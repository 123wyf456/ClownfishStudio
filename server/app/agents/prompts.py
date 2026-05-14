from app.schemas import CandidateItem, ContextSnapshot, UserMusicMemory

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
The first item must be a warm opening narration that introduces Clownfish,
mentions the user's city, date, weather, listening state, and why the selected
tracks fit this moment.
Add short bridge narrations between tracks so the program feels hosted rather
than like a plain playlist.
For every playable item, write a concrete explanation based on context, user
memory, tags, and candidate metadata. Do not mention internal tool IDs in
user-facing narration, but do set candidate_id exactly for playable items.
Match the user's language. If the locale or free text suggests Chinese, prefer
natural spoken Simplified Chinese for titles, summaries, and narration.
Return a radio program draft with title, summary, and blocks. The server will
add program_id, context_snapshot, total_duration_minutes, and generated_at.
""".strip()


def build_radio_prompt(
    context_snapshot: ContextSnapshot,
    memory: UserMusicMemory,
    history: list[dict[str, str]],
    candidate_items: list[CandidateItem],
) -> str:
    preference_candidates = [
        candidate for candidate in candidate_items if _is_preference_candidate(candidate)
    ]
    candidate_lines = [
        (
            f"- {candidate.candidate_id}: {candidate.title} by {candidate.creator}; "
            f"type={candidate.content_type.value}; tags={candidate.tags}; "
            f"source={candidate.source}; duration_seconds={candidate.duration_seconds}"
        )
        for candidate in candidate_items
    ]
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
            context_snapshot.model_dump_json(),
            "",
            "User music memory:",
            memory.model_dump_json(),
            "",
            "Recent history:",
            str(history),
            "",
            "Preference anchor candidates from the user's real NetEase taste:",
            "\n".join(preference_candidate_lines) if preference_candidate_lines else "None",
            "",
            "Candidate items:",
            "\n".join(candidate_lines),
        ]
    )


def _is_preference_candidate(candidate: CandidateItem) -> bool:
    preference_tags = {"user_preference", "recent_favorite", "liked_track", "playlist_seed"}
    return any(tag.lower() in preference_tags for tag in candidate.tags)
