import json
from urllib.error import HTTPError

from app.core.config import Settings
from app.services import providers as providers_module


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        del exc_type, exc, tb
        return False


def test_weather_provider_is_disabled_even_when_openweather_is_configured(monkeypatch) -> None:
    settings = Settings(
        weather_provider="openweather",
        openweather_api_key="weather-key",
    )

    def fake_urlopen(request, timeout=15):  # noqa: ANN001
        del request, timeout
        raise AssertionError("weather lookup should be disabled")

    monkeypatch.setattr(providers_module, "urlopen", fake_urlopen)

    provider = providers_module.build_weather_provider(settings)
    weather = provider.get_weather("Shanghai")

    assert weather == {
        "city": "Unknown",
        "condition": "unknown",
        "temperature_celsius": None,
        "humidity": None,
        "source": "disabled",
    }


def test_runtime_status_reports_weather_disabled() -> None:
    runtime = providers_module.build_runtime_status(
        Settings(weather_provider="openweather", openweather_api_key="weather-key")
    )

    assert runtime.weather.provider == "disabled"
    assert runtime.weather.mode == "disabled"
    assert runtime.weather.configured is False


def test_fish_audio_provider_returns_text_only_on_http_error(monkeypatch, tmp_path) -> None:
    settings = Settings(
        tts_provider="fish_audio",
        fish_audio_api_key="fish-key",
    )

    def fake_urlopen(request, timeout=45):  # noqa: ANN001
        del request, timeout
        raise HTTPError(
            url="https://api.fish.audio/v1/tts",
            code=402,
            msg="Insufficient Balance",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(providers_module, "AUDIO_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(providers_module, "urlopen", fake_urlopen)

    provider = providers_module.FishAudioTtsProvider(settings)
    audio_url, normalized_text = provider.synthesize("Hello from ClownfishStudio")

    assert audio_url is None
    assert normalized_text == "Hello from ClownfishStudio"
    assert list(tmp_path.iterdir()) == []


def test_fish_audio_provider_writes_mp3_file(monkeypatch, tmp_path) -> None:
    settings = Settings(
        tts_provider="fish_audio",
        fish_audio_api_key="fish-key",
        fish_audio_voice_id="voice-001",
    )

    def fake_urlopen(request, timeout=45):  # noqa: ANN001
        del timeout
        payload = json.loads(request.data.decode("utf-8"))
        assert payload["reference_id"] == "voice-001"
        assert payload["format"] == "mp3"
        return FakeResponse(b"ID3fake-mp3-data")

    monkeypatch.setattr(providers_module, "AUDIO_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(providers_module, "urlopen", fake_urlopen)

    provider = providers_module.FishAudioTtsProvider(settings)
    audio_url, normalized_text = provider.synthesize("ClownfishStudio on air")

    assert normalized_text == "ClownfishStudio on air"
    assert audio_url is not None
    created_files = list(tmp_path.iterdir())
    assert len(created_files) == 1
    assert created_files[0].read_bytes() == b"ID3fake-mp3-data"


def test_fish_audio_provider_accepts_full_tts_endpoint(monkeypatch, tmp_path) -> None:
    settings = Settings(
        tts_provider="fish_audio",
        fish_audio_api_key="fish-key",
        fish_audio_base_url="https://api.fish.audio/v1/tts",
    )

    def fake_urlopen(request, timeout=45):  # noqa: ANN001
        del timeout
        assert request.full_url == "https://api.fish.audio/v1/tts"
        return FakeResponse(b"ID3endpoint-ok")

    monkeypatch.setattr(providers_module, "AUDIO_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(providers_module, "urlopen", fake_urlopen)

    provider = providers_module.FishAudioTtsProvider(settings)
    audio_url, normalized_text = provider.synthesize("endpoint test")

    assert normalized_text == "endpoint test"
    assert audio_url is not None
