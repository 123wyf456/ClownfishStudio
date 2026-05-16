import os

from fastapi.testclient import TestClient

from app.core.config import ENV_FILE, get_settings
from app.main import app


def _capture_env_file() -> str | None:
    if not ENV_FILE.exists():
        return None
    return ENV_FILE.read_text(encoding="utf-8")


def _restore_env_file(original_env: str | None) -> None:
    if original_env is None:
        ENV_FILE.unlink(missing_ok=True)
        return
    ENV_FILE.write_text(original_env, encoding="utf-8")


def test_get_config_returns_desktop_configuration() -> None:
    client = TestClient(app)

    response = client.get("/api/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["radio_agent_provider"] == "mock"
    assert payload["config"]["tts_provider"] == "mock"
    assert payload["sections"]["music"]["provider"] == "netease_cloud_music"


def test_legacy_deepseek_config_maps_to_openai_provider() -> None:
    original_env = _capture_env_file()
    try:
        ENV_FILE.write_text(
            "\n".join(
                [
                    "RADIO_AGENT_PROVIDER=deepseek",
                    "RADIO_AGENT_MODEL=deepseek-chat",
                    "OPENAI_BASE_URL=https://api.openai.com/v1",
                    "DEEPSEEK_API_KEY=legacy-deepseek-key",
                    "DEEPSEEK_BASE_URL=https://api.deepseek.com",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        for key in [
            "RADIO_AGENT_PROVIDER",
            "RADIO_AGENT_MODEL",
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "DEEPSEEK_API_KEY",
            "DEEPSEEK_BASE_URL",
        ]:
            os.environ.pop(key, None)
        get_settings.cache_clear()

        settings = get_settings()

        assert settings.radio_agent_provider == "openai"
        assert settings.radio_agent_model == "deepseek-chat"
        assert settings.openai_api_key == "legacy-deepseek-key"
        assert settings.openai_base_url == "https://api.deepseek.com"
    finally:
        _restore_env_file(original_env)
        os.environ["RADIO_AGENT_PROVIDER"] = "mock"
        os.environ["RADIO_AGENT_MODEL"] = "test-model"
        os.environ["OPENAI_API_KEY"] = ""
        get_settings.cache_clear()


def test_put_config_updates_env_and_runtime_state() -> None:
    original_env = _capture_env_file()
    client = TestClient(app)

    try:
        response = client.put(
            "/api/config",
            json={
                "radio_agent_provider": "anthropic",
                "radio_agent_model": "claude-sonnet-4-20250514",
                "anthropic_api_key": "anthropic-test-key",
                "anthropic_base_url": "https://api.anthropic.com",
                "tts_provider": "fish_audio",
                "fish_audio_api_key": "fish-key",
                "fish_audio_base_url": "https://api.fish.audio",
                "fish_audio_voice_id": "voice-001",
                "calendar_provider": "feishu",
                "feishu_app_id": "app-id",
                "feishu_app_secret": "app-secret",
                "feishu_calendar_id": "calendar-id",
                "weather_provider": "openweather",
                "openweather_api_key": "weather-key",
                "openweather_base_url": "https://api.openweathermap.org",
                "netease_api_base_url": "http://localhost:3000",
                "netease_cookie": "MUSIC_U=test-cookie",
                "netease_playback_level": "exhigh",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["config"]["radio_agent_provider"] == "anthropic"
        assert payload["config"]["tts_provider"] == "fish_audio"
        assert payload["config"]["calendar_provider"] == "feishu"
        assert payload["config"]["weather_provider"] == "disabled"
        assert payload["config"]["openweather_api_key"] is None
        assert payload["config"]["netease_playback_level"] == "exhigh"
        assert payload["sections"]["brain"]["configured"] is True
        assert payload["sections"]["tts"]["configured"] is True
        assert payload["sections"]["weather"]["configured"] is False

        get_settings.cache_clear()
        settings = get_settings()
        assert settings.radio_agent_provider == "anthropic"
        assert settings.anthropic_api_key == "anthropic-test-key"
        assert settings.openweather_api_key is None
        assert settings.netease_cookie == "MUSIC_U=test-cookie"
        assert "OPENWEATHER_API_KEY=" in ENV_FILE.read_text(encoding="utf-8")
        assert "NETEASE_PLAYBACK_LEVEL=exhigh" in ENV_FILE.read_text(encoding="utf-8")
    finally:
        _restore_env_file(original_env)
        for key in [
            "RADIO_AGENT_PROVIDER",
            "RADIO_AGENT_MODEL",
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
        ]:
            if key != "RADIO_AGENT_PROVIDER":
                os.environ.pop(key, None)
        os.environ["RADIO_AGENT_PROVIDER"] = "mock"
        os.environ["RADIO_AGENT_MODEL"] = "test-model"
        os.environ["OPENAI_API_KEY"] = ""
        os.environ["ANTHROPIC_API_KEY"] = ""
        os.environ["NETEASE_API_BASE_URL"] = ""
        os.environ["TTS_PROVIDER"] = "mock"
        os.environ["CALENDAR_PROVIDER"] = "mock"
        os.environ["WEATHER_PROVIDER"] = "mock"
        get_settings.cache_clear()
