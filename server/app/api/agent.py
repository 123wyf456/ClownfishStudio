from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas import MusicHealthResponse
from app.services.providers import build_music_health, build_runtime_status

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("/status")
def agent_status() -> dict[str, str | bool]:
    settings = get_settings()
    runtime = build_runtime_status()
    live_key_configured = (
        bool(settings.deepseek_api_key)
        if settings.radio_agent_provider == "deepseek"
        else bool(settings.openai_api_key)
    )
    active_mode = settings.radio_agent_provider if runtime.brain.configured else "not_configured"
    return {
        "provider": settings.radio_agent_provider,
        "model": (
            settings.deepseek_model
            if settings.radio_agent_provider == "deepseek"
            else settings.radio_agent_model
        ),
        "openai_configured": live_key_configured,
        "active_mode": active_mode,
        "uses_model": active_mode in {"codex", "openai", "deepseek"},
        "configuration_issue": (
            "model API key is missing"
            if settings.radio_agent_provider != "mock" and not runtime.brain.configured
            else ""
        ),
    }


@router.get("/music", response_model=MusicHealthResponse)
def music_status() -> MusicHealthResponse:
    return build_music_health()
