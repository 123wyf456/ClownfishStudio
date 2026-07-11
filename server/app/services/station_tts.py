from __future__ import annotations

from app.schemas import StationSession
from app.services.providers import build_tts_provider


def synthesize_session_text(
    *,
    session: StationSession,
    text: str,
) -> StationSession:
    provider = build_tts_provider()
    audio_url, normalized_text = provider.synthesize(text)
    return session.model_copy(
        update={
            "tts_text": normalized_text or None,
            "tts_audio_url": audio_url,
        }
    )
