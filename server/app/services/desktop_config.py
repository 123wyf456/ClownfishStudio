from __future__ import annotations

import os
from collections import OrderedDict

from app.core.config import ENV_FILE, get_settings
from app.schemas import (
    DesktopConfigResponse,
    DesktopConfigSection,
    DesktopConfigUpdateRequest,
    DesktopConfigValue,
)
from app.services.providers import build_runtime_status

CONFIG_KEY_ORDER = [
    "RADIO_AGENT_PROVIDER",
    "RADIO_AGENT_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
    "TTS_PROVIDER",
    "FISH_AUDIO_API_KEY",
    "FISH_AUDIO_BASE_URL",
    "FISH_AUDIO_VOICE_ID",
    "CALENDAR_PROVIDER",
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    "FEISHU_CALENDAR_ID",
    "WEATHER_PROVIDER",
    "OPENWEATHER_API_KEY",
    "OPENWEATHER_BASE_URL",
    "NETEASE_API_BASE_URL",
    "NETEASE_COOKIE",
    "NETEASE_PLAYBACK_LEVEL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
]


def get_desktop_config() -> DesktopConfigResponse:
    settings = get_settings()
    runtime = build_runtime_status(settings)
    config = DesktopConfigValue(
        radio_agent_provider=settings.radio_agent_provider,
        radio_agent_model=settings.radio_agent_model,
        openai_api_key=settings.openai_api_key,
        openai_base_url=settings.openai_base_url,
        anthropic_api_key=settings.anthropic_api_key,
        anthropic_base_url=settings.anthropic_base_url,
        tts_provider=settings.tts_provider,
        fish_audio_api_key=settings.fish_audio_api_key,
        fish_audio_base_url=settings.fish_audio_base_url,
        fish_audio_voice_id=settings.fish_audio_voice_id,
        calendar_provider=settings.calendar_provider,
        feishu_app_id=settings.feishu_app_id,
        feishu_app_secret=settings.feishu_app_secret,
        feishu_calendar_id=settings.feishu_calendar_id,
        weather_provider="disabled",
        openweather_api_key=None,
        openweather_base_url=settings.openweather_base_url,
        netease_api_base_url=settings.netease_api_base_url,
        netease_cookie=settings.netease_cookie,
        netease_playback_level=settings.netease_playback_level,
    )

    return DesktopConfigResponse(
        config=config,
        runtime=runtime,
        sections={
            "brain": DesktopConfigSection(
                provider=runtime.brain.provider,
                configured=runtime.brain.configured,
            ),
            "tts": DesktopConfigSection(
                provider=runtime.tts.provider,
                configured=runtime.tts.configured,
            ),
            "calendar": DesktopConfigSection(
                provider=runtime.calendar.provider,
                configured=runtime.calendar.configured,
            ),
            "weather": DesktopConfigSection(
                provider=runtime.weather.provider,
                configured=runtime.weather.configured,
            ),
            "music": DesktopConfigSection(
                provider=runtime.music.provider,
                configured=runtime.music.configured,
            ),
        },
    )


def update_desktop_config(payload: DesktopConfigUpdateRequest) -> DesktopConfigResponse:
    updated_values = OrderedDict(
        [
            ("RADIO_AGENT_PROVIDER", payload.radio_agent_provider),
            ("RADIO_AGENT_MODEL", payload.radio_agent_model),
            ("OPENAI_API_KEY", payload.openai_api_key),
            ("OPENAI_BASE_URL", payload.openai_base_url),
            ("ANTHROPIC_API_KEY", payload.anthropic_api_key),
            ("ANTHROPIC_BASE_URL", payload.anthropic_base_url),
            ("TTS_PROVIDER", payload.tts_provider),
            ("FISH_AUDIO_API_KEY", payload.fish_audio_api_key),
            ("FISH_AUDIO_BASE_URL", payload.fish_audio_base_url),
            ("FISH_AUDIO_VOICE_ID", payload.fish_audio_voice_id),
            ("CALENDAR_PROVIDER", payload.calendar_provider),
            ("FEISHU_APP_ID", payload.feishu_app_id),
            ("FEISHU_APP_SECRET", payload.feishu_app_secret),
            ("FEISHU_CALENDAR_ID", payload.feishu_calendar_id),
            ("WEATHER_PROVIDER", "disabled"),
            ("OPENWEATHER_API_KEY", None),
            ("OPENWEATHER_BASE_URL", payload.openweather_base_url),
            ("NETEASE_API_BASE_URL", payload.netease_api_base_url),
            ("NETEASE_COOKIE", payload.netease_cookie),
            ("NETEASE_PLAYBACK_LEVEL", payload.netease_playback_level),
            ("DEEPSEEK_API_KEY", None),
            ("DEEPSEEK_BASE_URL", None),
            ("DEEPSEEK_MODEL", None),
        ]
    )
    _write_env_values(updated_values)
    _write_process_env(updated_values)
    get_settings.cache_clear()
    return get_desktop_config()


def _write_env_values(updated_values: OrderedDict[str, str | None]) -> None:
    existing_lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    rewritten_lines: list[str] = []
    seen_keys: set[str] = set()
    for raw_line in existing_lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw_line:
            rewritten_lines.append(raw_line)
            continue

        key = raw_line.split("=", 1)[0].strip()
        if key not in updated_values:
            rewritten_lines.append(raw_line)
            continue

        rewritten_lines.append(f"{key}={_normalize_env_value(updated_values[key])}")
        seen_keys.add(key)

    for key in CONFIG_KEY_ORDER:
        if key in updated_values and key not in seen_keys:
            rewritten_lines.append(f"{key}={_normalize_env_value(updated_values[key])}")

    ENV_FILE.write_text("\n".join(rewritten_lines).rstrip() + "\n", encoding="utf-8")


def _normalize_env_value(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(part.strip() for part in value.splitlines() if part.strip())


def _write_process_env(updated_values: OrderedDict[str, str | None]) -> None:
    for key, value in updated_values.items():
        normalized = _normalize_env_value(value)
        if normalized:
            os.environ[key] = normalized
            continue
        os.environ.pop(key, None)
