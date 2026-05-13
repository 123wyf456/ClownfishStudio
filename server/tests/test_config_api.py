import os

from fastapi.testclient import TestClient

from app.core.config import ENV_FILE, get_settings
from app.main import app


def test_get_config_returns_desktop_configuration() -> None:
    client = TestClient(app)

    response = client.get("/api/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["radio_agent_provider"] == "mock"
    assert payload["config"]["tts_provider"] == "mock"
    assert payload["sections"]["music"]["provider"] == "netease_cloud_music"


def test_put_config_updates_env_and_runtime_state() -> None:
    original_env = ENV_FILE.read_text(encoding="utf-8")
    client = TestClient(app)

    try:
        response = client.put(
            "/api/config",
            json={
                "radio_agent_provider": "deepseek",
                "radio_agent_model": "deepseek-v4-flash",
                "deepseek_api_key": "deepseek-test-key",
                "deepseek_base_url": "https://api.deepseek.com",
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
        assert payload["config"]["radio_agent_provider"] == "deepseek"
        assert payload["config"]["tts_provider"] == "fish_audio"
        assert payload["config"]["calendar_provider"] == "feishu"
        assert payload["config"]["netease_playback_level"] == "exhigh"
        assert payload["sections"]["brain"]["configured"] is True
        assert payload["sections"]["tts"]["configured"] is True

        get_settings.cache_clear()
        settings = get_settings()
        assert settings.radio_agent_provider == "deepseek"
        assert settings.deepseek_api_key == "deepseek-test-key"
        assert settings.netease_cookie == "MUSIC_U=test-cookie"
        assert "NETEASE_PLAYBACK_LEVEL=exhigh" in ENV_FILE.read_text(encoding="utf-8")
    finally:
        ENV_FILE.write_text(original_env, encoding="utf-8")
        for key in [
            "RADIO_AGENT_PROVIDER",
            "RADIO_AGENT_MODEL",
            "DEEPSEEK_API_KEY",
            "DEEPSEEK_BASE_URL",
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
        os.environ["DEEPSEEK_API_KEY"] = ""
        os.environ["NETEASE_API_BASE_URL"] = ""
        os.environ["TTS_PROVIDER"] = "mock"
        os.environ["CALENDAR_PROVIDER"] = "mock"
        os.environ["WEATHER_PROVIDER"] = "mock"
        get_settings.cache_clear()
