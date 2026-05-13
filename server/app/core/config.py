import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

SERVER_ROOT = Path(__file__).resolve().parents[2]


def _resolve_runtime_root() -> Path:
    configured_root = os.environ.get("CLOWNFISH_RUNTIME_ROOT")
    if configured_root:
        return Path(configured_root).expanduser().resolve()
    return SERVER_ROOT


def _build_default_database_url(runtime_root: Path) -> str:
    database_path = (runtime_root / "clownfishstudio.db").resolve()
    return f"sqlite:///{database_path.as_posix()}"


RUNTIME_ROOT = _resolve_runtime_root()
ENV_FILE = RUNTIME_ROOT / ".env"


class Settings(BaseModel):
    app_name: str = Field(default="ClownfishStudio")
    app_env: Literal["development", "test", "production"] = Field(default="development")
    log_level: str = Field(default="INFO")
    database_url: str = Field(default="sqlite:///./clownfishstudio.db")
    openai_api_key: str | None = Field(default=None)
    openai_base_url: str = Field(default="https://api.openai.com/v1")
    radio_agent_provider: Literal["mock", "codex", "openai", "deepseek"] = Field(default="mock")
    radio_agent_model: str = Field(default="codex-mini-latest")
    deepseek_api_key: str | None = Field(default=None)
    deepseek_base_url: str = Field(default="https://api.deepseek.com")
    deepseek_model: str = Field(default="deepseek-chat")
    tts_provider: Literal["mock", "fish_audio"] = Field(default="mock")
    fish_audio_api_key: str | None = Field(default=None)
    fish_audio_base_url: str = Field(default="https://api.fish.audio")
    fish_audio_voice_id: str | None = Field(default=None)
    calendar_provider: Literal["mock", "feishu"] = Field(default="mock")
    feishu_app_id: str | None = Field(default=None)
    feishu_app_secret: str | None = Field(default=None)
    feishu_calendar_id: str | None = Field(default=None)
    weather_provider: Literal["mock", "openweather"] = Field(default="mock")
    openweather_api_key: str | None = Field(default=None)
    openweather_base_url: str = Field(default="https://api.openweathermap.org")
    netease_api_base_url: str | None = Field(default=None)
    netease_cookie: str | None = Field(default=None)
    netease_playback_level: str = Field(default="standard")


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


@lru_cache
def get_settings() -> Settings:
    env_values = _read_env_file(ENV_FILE)
    default_database_url = _build_default_database_url(RUNTIME_ROOT)
    configured_provider = os.environ.get("RADIO_AGENT_PROVIDER") or env_values.get(
        "RADIO_AGENT_PROVIDER", "mock"
    )

    def read_value(name: str, default: str | None = None) -> str | None:
        if name in os.environ:
            return os.environ[name]
        return env_values.get(name) or default

    return Settings(
        app_name=read_value("APP_NAME", "ClownfishStudio") or "ClownfishStudio",
        app_env=read_value("APP_ENV", "development") or "development",
        log_level=read_value("LOG_LEVEL", "INFO") or "INFO",
        database_url=read_value("DATABASE_URL", default_database_url) or default_database_url,
        openai_api_key=read_value("OPENAI_API_KEY"),
        openai_base_url=read_value("OPENAI_BASE_URL", "https://api.openai.com/v1")
        or "https://api.openai.com/v1",
        radio_agent_provider=configured_provider or "mock",
        radio_agent_model=read_value("RADIO_AGENT_MODEL", "codex-mini-latest")
        or "codex-mini-latest",
        deepseek_api_key=read_value("DEEPSEEK_API_KEY")
        or (read_value("OPENAI_API_KEY") if configured_provider == "deepseek" else None),
        deepseek_base_url=read_value("DEEPSEEK_BASE_URL")
        or (read_value("OPENAI_BASE_URL") if configured_provider == "deepseek" else None)
        or "https://api.deepseek.com",
        deepseek_model=read_value("DEEPSEEK_MODEL")
        or (read_value("RADIO_AGENT_MODEL") if configured_provider == "deepseek" else None)
        or "deepseek-chat",
        tts_provider=read_value("TTS_PROVIDER", "mock") or "mock",
        fish_audio_api_key=read_value("FISH_AUDIO_API_KEY"),
        fish_audio_base_url=read_value("FISH_AUDIO_BASE_URL", "https://api.fish.audio")
        or "https://api.fish.audio",
        fish_audio_voice_id=read_value("FISH_AUDIO_VOICE_ID"),
        calendar_provider=read_value("CALENDAR_PROVIDER", "mock") or "mock",
        feishu_app_id=read_value("FEISHU_APP_ID"),
        feishu_app_secret=read_value("FEISHU_APP_SECRET"),
        feishu_calendar_id=read_value("FEISHU_CALENDAR_ID"),
        weather_provider=read_value("WEATHER_PROVIDER", "mock") or "mock",
        openweather_api_key=read_value("OPENWEATHER_API_KEY"),
        openweather_base_url=read_value(
            "OPENWEATHER_BASE_URL",
            "https://api.openweathermap.org",
        )
        or "https://api.openweathermap.org",
        netease_api_base_url=read_value("NETEASE_API_BASE_URL"),
        netease_cookie=read_value("NETEASE_COOKIE"),
        netease_playback_level=read_value("NETEASE_PLAYBACK_LEVEL", "standard") or "standard",
    )
