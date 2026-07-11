from datetime import UTC, datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Mood(StrEnum):
    calm = "calm"
    tired = "tired"
    focused = "focused"
    happy = "happy"
    anxious = "anxious"
    nostalgic = "nostalgic"


class ListeningNeed(StrEnum):
    relax = "relax"
    focus = "focus"
    commute = "commute"
    workout = "workout"
    sleep = "sleep"
    discover = "discover"
    companionship = "companionship"


class ContentType(StrEnum):
    music = "music"
    podcast = "podcast"


class ProgramItemType(StrEnum):
    narration = "narration"
    music = "music"
    podcast = "podcast"


class PlaylistItemSource(StrEnum):
    initial = "initial"
    refill = "refill"
    user_request = "user_request"


class PlaylistRecommendationKind(StrEnum):
    real_recommendation = "real_recommendation"
    real_search = "real_search"
    mock_fallback = "mock_fallback"


class PlayerAdvanceReason(StrEnum):
    ended = "ended"
    next = "next"
    previous = "previous"
    skip = "skip"


class FeedbackType(StrEnum):
    like = "like"
    dislike = "dislike"
    skip = "skip"
    too_familiar = "too_familiar"
    want_more_like_this = "want_more_like_this"
    less_like_this = "less_like_this"


class DeviceContext(StrictSchema):
    local_time: datetime
    timezone: str = Field(min_length=1, examples=["Asia/Shanghai"])
    locale: str | None = Field(default=None, examples=["zh-CN"])
    city_hint: str | None = Field(default=None, examples=["Shanghai"])
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class CalendarEvent(StrictSchema):
    event_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    start_at: datetime
    end_at: datetime | None = None
    location: str | None = None
    source: str = Field(min_length=1)


class UserStateInput(StrictSchema):
    mood: Mood | None = None
    energy_level: int | None = Field(default=None, ge=1, le=5)
    needs: list[ListeningNeed] = Field(default_factory=list)
    duration_minutes: int = Field(default=30, ge=5, le=180)
    free_text: str | None = Field(default=None, max_length=1000)


class ContextSnapshot(StrictSchema):
    device_context: DeviceContext
    user_state: UserStateInput
    weather: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    calendar_events: list[CalendarEvent] = Field(default_factory=list)
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UserMusicMemory(StrictSchema):
    user_id: str = Field(min_length=1)
    favorite_genres: list[str] = Field(default_factory=list)
    favorite_artists: list[str] = Field(default_factory=list)
    disliked_artists: list[str] = Field(default_factory=list)
    recent_candidate_ids: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CandidateItem(StrictSchema):
    candidate_id: str = Field(min_length=1)
    content_type: ContentType
    title: str = Field(min_length=1)
    creator: str = Field(min_length=1)
    duration_seconds: int | None = Field(default=None, ge=1)
    playback_url: str | None = None
    tags: list[str] = Field(default_factory=list)
    source: str = Field(min_length=1)
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class ProgramItem(StrictSchema):
    item_id: str = Field(min_length=1)
    item_type: ProgramItemType
    title: str = Field(min_length=1)
    creator: str | None = None
    position: int = Field(ge=0)
    candidate_id: str | None = None
    playback_url: str | None = None
    duration_seconds: int | None = Field(default=None, ge=1)
    narration_text: str | None = Field(default=None, max_length=2000)
    explanation: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_item_payload(self) -> Self:
        if self.item_type is ProgramItemType.narration and not self.narration_text:
            raise ValueError("narration program items require narration_text")

        if (
            self.item_type in {ProgramItemType.music, ProgramItemType.podcast}
            and not self.candidate_id
        ):
            raise ValueError("music and podcast program items require candidate_id")

        return self


class ProgramBlock(StrictSchema):
    block_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str | None = Field(default=None, max_length=1000)
    position: int = Field(ge=0)
    items: list[ProgramItem] = Field(default_factory=list)


class RadioProgram(StrictSchema):
    program_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=2000)
    context_snapshot: ContextSnapshot
    blocks: list[ProgramBlock] = Field(min_length=1)
    total_duration_minutes: int = Field(ge=1, le=240)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PlaylistItem(StrictSchema):
    item_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    creator: str = Field(min_length=1)
    duration_seconds: int | None = Field(default=None, ge=1)
    playback_url: str | None = None
    source: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    inserted_by: PlaylistItemSource = PlaylistItemSource.initial
    recommendation_kind: PlaylistRecommendationKind = PlaylistRecommendationKind.real_search
    added_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RadioPlaylist(StrictSchema):
    playlist_id: str = Field(min_length=1)
    items: list[PlaylistItem] = Field(default_factory=list)
    current_index: int = Field(default=0, ge=0)
    target_size: int = Field(default=8, ge=1, le=100)
    refill_threshold: int = Field(default=3, ge=0, le=99)
    revision: int = Field(default=0, ge=0)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_current_index(self) -> Self:
        if len(self.items) > self.target_size:
            raise ValueError("playlist items cannot exceed target_size")
        if self.items and self.current_index >= len(self.items):
            raise ValueError("playlist current_index must point to an item")
        if self.refill_threshold >= self.target_size:
            raise ValueError("playlist refill_threshold must be smaller than target_size")
        return self


class FeedbackEvent(StrictSchema):
    feedback_type: FeedbackType
    user_id: str = Field(min_length=1)
    program_id: str = Field(min_length=1)
    item_id: str | None = None
    candidate_id: str | None = None
    comment: str | None = Field(default=None, max_length=1000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FeedbackResponse(StrictSchema):
    feedback: FeedbackEvent
    memory_update_hint: dict[str, str]


class GenerateProgramRequest(StrictSchema):
    user_id: str = Field(min_length=1)
    device_context: DeviceContext
    user_state: UserStateInput
    max_candidates: int = Field(default=20, ge=1, le=50)


class GenerateProgramResponse(StrictSchema):
    request_id: str = Field(min_length=1)
    program: RadioProgram
    candidate_count: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)
    candidate_items: list[CandidateItem] = Field(default_factory=list, exclude=True)


class IntegrationStatus(StrictSchema):
    provider: str = Field(min_length=1)
    configured: bool
    mode: str = Field(min_length=1)
    detail: str = Field(default="")


class RuntimeStatus(StrictSchema):
    app_name: str = Field(min_length=1)
    brain: IntegrationStatus
    tts: IntegrationStatus
    calendar: IntegrationStatus
    weather: IntegrationStatus
    music: IntegrationStatus


class MusicAccountStatus(StrictSchema):
    connected: bool
    anonymous: bool
    user_id: str | None = None
    nickname: str | None = None
    has_profile: bool
    detail: str = ""


class MusicPreferenceStatus(StrictSchema):
    can_read_profile: bool = False
    can_read_playlists: bool = False
    can_read_liked_playlist: bool = False
    can_read_liked_songs: bool = False
    can_read_history: bool = False
    can_read_daily_recommendations: bool = False
    can_read_personalized_new_songs: bool = False
    can_read_recommended_playlists: bool = False
    playlist_count: int = 0
    liked_playlist_track_count: int = 0
    history_count: int = 0
    daily_recommendation_count: int = 0
    personalized_new_song_count: int = 0
    recommended_playlist_count: int = 0
    sample_playlist_names: list[str] = Field(default_factory=list)
    detail: str = ""


class MusicHealthResponse(StrictSchema):
    provider: str = Field(min_length=1)
    base_url: str | None = None
    search_ok: bool
    playback_ok: bool
    account: MusicAccountStatus
    preference_status: MusicPreferenceStatus = Field(default_factory=MusicPreferenceStatus)


class DesktopConfigSection(StrictSchema):
    provider: str
    configured: bool


class DesktopConfigValue(StrictSchema):
    radio_agent_provider: str
    radio_agent_model: str
    openai_api_key: str | None = None
    openai_base_url: str
    anthropic_api_key: str | None = None
    anthropic_base_url: str
    tts_provider: str
    fish_audio_api_key: str | None = None
    fish_audio_base_url: str
    fish_audio_voice_id: str | None = None
    calendar_provider: str
    feishu_app_id: str | None = None
    feishu_app_secret: str | None = None
    feishu_calendar_id: str | None = None
    weather_provider: str
    openweather_api_key: str | None = None
    openweather_base_url: str
    netease_api_base_url: str | None = None
    netease_cookie: str | None = None
    netease_playback_level: str


class DesktopConfigResponse(StrictSchema):
    config: DesktopConfigValue
    runtime: RuntimeStatus
    sections: dict[str, DesktopConfigSection]


class DesktopConfigUpdateRequest(StrictSchema):
    radio_agent_provider: str
    radio_agent_model: str
    openai_api_key: str | None = None
    openai_base_url: str = Field(default="https://api.openai.com/v1")
    anthropic_api_key: str | None = None
    anthropic_base_url: str = Field(default="https://api.anthropic.com")
    tts_provider: str
    fish_audio_api_key: str | None = None
    fish_audio_base_url: str
    fish_audio_voice_id: str | None = None
    calendar_provider: str
    feishu_app_id: str | None = None
    feishu_app_secret: str | None = None
    feishu_calendar_id: str | None = None
    weather_provider: str
    openweather_api_key: str | None = None
    openweather_base_url: str
    netease_api_base_url: str | None = None
    netease_cookie: str | None = None
    netease_playback_level: str = Field(min_length=1)


class ChatMessage(StrictSchema):
    role: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=4000)
    metadata: "ReplyMetadata | None" = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReplyMetadata(StrictSchema):
    reply_kind: str = Field(min_length=1, max_length=80)
    reply_source: str = Field(min_length=1, max_length=80)
    playlist_changed: bool = False
    event_id: str | None = Field(default=None, min_length=1, max_length=120)


class StationSessionEvent(StrictSchema):
    event_id: str = Field(min_length=1, max_length=120)
    event_type: str = Field(min_length=1, max_length=80)
    payload: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChatMusicConstraints(StrictSchema):
    artists: list[str] = Field(default_factory=list)
    tracks: list[str] = Field(default_factory=list)
    genres: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    scenes: list[str] = Field(default_factory=list)
    mood: str | None = Field(default=None, max_length=80)
    energy: str | None = Field(default=None, max_length=80)
    avoid: list[str] = Field(default_factory=list)
    raw_query: str | None = Field(default=None, max_length=1000)


class ChatRouterResult(StrictSchema):
    emotion: str | None = Field(default=None, max_length=80)
    need_chat: bool = False
    need_music: bool = False
    need_info: bool = False
    need_control: bool = False
    control_action: str | None = Field(default=None, max_length=80)
    music_constraints: ChatMusicConstraints = Field(default_factory=ChatMusicConstraints)
    confidence: float = Field(default=0.5, ge=0, le=1)


class StationSession(StrictSchema):
    session_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    greeting: str = Field(min_length=1)
    tts_text: str | None = None
    tts_audio_url: str | None = None
    program: RadioProgram | None = None
    playlist: RadioPlaylist | None = None
    weather: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    calendar_events: list[CalendarEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    events: list[StationSessionEvent] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StationGenerateResponse(StrictSchema):
    session: StationSession
    candidate_count: int = Field(ge=0)
    runtime: RuntimeStatus


class StationChatRequest(StrictSchema):
    user_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=4000)
    device_context: DeviceContext


class StationChatResponse(StrictSchema):
    reply: ChatMessage
    session: StationSession
    runtime: RuntimeStatus


class PlayerNowResponse(StrictSchema):
    session: StationSession | None = None
    current_item: PlaylistItem | ProgramItem | None = None
    queue: list[PlaylistItem | ProgramItem] = Field(default_factory=list)
    playlist: RadioPlaylist | None = None
    runtime: RuntimeStatus


class PlayerAdvanceRequest(StrictSchema):
    item_id: str | None = Field(default=None, min_length=1)
    reason: PlayerAdvanceReason


class PlayerAdvanceResponse(StrictSchema):
    session: StationSession | None = None
    current_item: PlaylistItem | ProgramItem | None = None
    queue: list[PlaylistItem | ProgramItem] = Field(default_factory=list)
    playlist: RadioPlaylist | None = None
    runtime: RuntimeStatus
    warnings: list[str] = Field(default_factory=list)
