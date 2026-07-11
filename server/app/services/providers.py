from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from app.core.config import RUNTIME_ROOT, Settings, get_settings
from app.schemas import (
    CalendarEvent,
    DeviceContext,
    IntegrationStatus,
    MusicHealthResponse,
    RuntimeStatus,
)
from app.tools.netease_music_tool import get_netease_music_health, is_netease_music_enabled
from app.tools.weather_tool import get_weather as get_mock_weather

AUDIO_OUTPUT_DIR = RUNTIME_ROOT / "generated_audio"


class WeatherProvider(Protocol):
    def get_weather(
        self,
        device_context: DeviceContext | str | None,
    ) -> dict[str, str | int | float | bool | None]:
        """Return weather facts for the current session."""


class CalendarProvider(Protocol):
    def get_events(self, user_id: str) -> list[CalendarEvent]:
        """Return near-term events that can shape the session."""


class TtsProvider(Protocol):
    def synthesize(self, text: str) -> tuple[str | None, str]:
        """Return audio url plus normalized text."""


WEATHER_DISABLED_SNAPSHOT: dict[str, str | int | float | bool | None] = {
    "city": "Unknown",
    "condition": "unknown",
    "temperature_celsius": None,
    "humidity": None,
    "source": "disabled",
}


class DisabledWeatherProvider:
    def get_weather(
        self,
        device_context: DeviceContext | str | None,
    ) -> dict[str, str | int | float | bool | None]:
        del device_context
        return dict(WEATHER_DISABLED_SNAPSHOT)


class MockWeatherProvider:
    def get_weather(
        self,
        device_context: DeviceContext | str | None,
    ) -> dict[str, str | int | float | bool | None]:
        return get_mock_weather(device_context)


class MockCalendarProvider:
    def get_events(self, user_id: str) -> list[CalendarEvent]:
        base_time = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        return [
            CalendarEvent(
                event_id=f"mock-calendar-{user_id}-1",
                title="Morning planning block",
                start_at=base_time + timedelta(hours=8),
                end_at=base_time + timedelta(hours=9),
                location="Home office",
                source="mock",
            ),
            CalendarEvent(
                event_id=f"mock-calendar-{user_id}-2",
                title="Evening reset walk",
                start_at=base_time + timedelta(hours=18),
                end_at=base_time + timedelta(hours=19),
                location="Neighborhood",
                source="mock",
            ),
        ]


class MockTtsProvider:
    def synthesize(self, text: str) -> tuple[str | None, str]:
        synthesized_id = uuid4().hex
        return (f"/mock-audio/{synthesized_id}.mp3", text.strip())


class OpenWeatherProvider:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._fallback = DisabledWeatherProvider()

    def get_weather(
        self,
        device_context: DeviceContext | str | None,
    ) -> dict[str, str | int | float | bool | None]:
        context = _normalize_weather_context(device_context)
        if not self._settings.openweather_api_key:
            return self._fallback.get_weather(device_context)

        params = {
            "appid": self._settings.openweather_api_key,
            "units": "metric",
        }
        normalized_city = context["city_hint"]
        if context["latitude"] is not None and context["longitude"] is not None:
            params["lat"] = str(context["latitude"])
            params["lon"] = str(context["longitude"])
        elif normalized_city:
            params["q"] = normalized_city
        else:
            return self._fallback.get_weather(device_context)

        url = (
            f"{self._settings.openweather_base_url.rstrip('/')}/data/2.5/weather?"
            f"{urlencode(params)}"
        )
        request = Request(url, headers={"Accept": "application/json"}, method="GET")

        try:
            with urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            return self._fallback.get_weather(device_context)

        if not isinstance(payload, dict):
            return self._fallback.get_weather(device_context)

        weather_items = payload.get("weather")
        main = payload.get("main")
        weather = weather_items[0] if isinstance(weather_items, list) and weather_items else {}
        condition = weather.get("main") if isinstance(weather, dict) else None
        city = payload.get("name")
        humidity = main.get("humidity") if isinstance(main, dict) else None
        temperature = main.get("temp") if isinstance(main, dict) else None
        normalized_result_city = (
            city if isinstance(city, str) and city.strip() else normalized_city or "Unknown"
        )

        return {
            "city": normalized_result_city,
            "condition": (
                condition.strip().lower()
                if isinstance(condition, str) and condition.strip()
                else "clear"
            ),
            "temperature_celsius": temperature if isinstance(temperature, int | float) else 0,
            "humidity": humidity / 100 if isinstance(humidity, int | float) else 0,
            "source": "openweather",
        }


class FishAudioTtsProvider:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        AUDIO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def synthesize(self, text: str) -> tuple[str | None, str]:
        normalized_text = text.strip()
        if not normalized_text or not self._settings.fish_audio_api_key:
            return (None, normalized_text)

        payload: dict[str, object] = {
            "text": normalized_text,
            "format": "mp3",
            "mp3_bitrate": 128,
            "normalize": True,
            "latency": "normal",
        }
        if self._settings.fish_audio_voice_id:
            payload["reference_id"] = self._settings.fish_audio_voice_id

        request = Request(
            _build_fish_audio_tts_endpoint(self._settings.fish_audio_base_url),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._settings.fish_audio_api_key}",
                "Content-Type": "application/json",
                "Accept": "audio/mpeg, application/octet-stream",
                "model": "s2-pro",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=45) as response:
                audio_bytes = response.read()
        except (HTTPError, URLError, TimeoutError):
            return (None, normalized_text)

        if not audio_bytes:
            return (None, normalized_text)

        filename = f"{uuid4().hex}.mp3"
        output_path = AUDIO_OUTPUT_DIR / filename
        output_path.write_bytes(audio_bytes)
        return (f"/generated-audio/{filename}", normalized_text)


def build_runtime_status(settings: Settings | None = None) -> RuntimeStatus:
    active_settings = settings or get_settings()
    brain_provider = active_settings.radio_agent_provider
    brain_configured = _is_brain_configured(active_settings)
    tts_provider = active_settings.tts_provider
    calendar_provider = active_settings.calendar_provider
    weather_provider = active_settings.weather_provider
    weather_configured = (
        weather_provider == "mock"
        or (
            weather_provider == "openweather"
            and bool(active_settings.openweather_api_key)
        )
    )

    return RuntimeStatus(
        app_name=active_settings.app_name,
        brain=IntegrationStatus(
            provider=brain_provider,
            configured=brain_configured,
            mode="live" if brain_configured and brain_provider != "mock" else "mock",
            detail=active_settings.radio_agent_model,
        ),
        tts=IntegrationStatus(
            provider=tts_provider,
            configured=tts_provider == "mock" or bool(active_settings.fish_audio_api_key),
            mode="live"
            if tts_provider == "fish_audio" and active_settings.fish_audio_api_key
            else "mock",
            detail=active_settings.fish_audio_voice_id or "",
        ),
        calendar=IntegrationStatus(
            provider=calendar_provider,
            configured=calendar_provider == "mock"
            or bool(active_settings.feishu_app_id and active_settings.feishu_app_secret),
            mode="live"
            if calendar_provider == "feishu"
            and active_settings.feishu_app_id
            and active_settings.feishu_app_secret
            else "mock",
            detail=active_settings.feishu_calendar_id or "",
        ),
        weather=IntegrationStatus(
            provider=weather_provider,
            configured=weather_configured,
            mode=(
                "live"
                if weather_provider == "openweather" and active_settings.openweather_api_key
                else weather_provider
            ),
            detail=(
                active_settings.openweather_base_url
                if weather_provider == "openweather"
                else ""
            ),
        ),
        music=IntegrationStatus(
            provider="netease_cloud_music",
            configured=is_netease_music_enabled(),
            mode="live" if is_netease_music_enabled() else "mock",
            detail=active_settings.netease_api_base_url or "",
        ),
    )


def build_music_health(settings: Settings | None = None) -> MusicHealthResponse:
    del settings
    return get_netease_music_health()


def build_weather_provider(settings: Settings | None = None) -> WeatherProvider:
    active_settings = settings or get_settings()
    if active_settings.weather_provider == "openweather" and active_settings.openweather_api_key:
        return OpenWeatherProvider(active_settings)
    if active_settings.weather_provider == "mock":
        return MockWeatherProvider()
    return DisabledWeatherProvider()


def build_calendar_provider(settings: Settings | None = None) -> CalendarProvider:
    del settings
    return MockCalendarProvider()


def build_tts_provider(settings: Settings | None = None) -> TtsProvider:
    active_settings = settings or get_settings()
    if active_settings.tts_provider == "fish_audio" and active_settings.fish_audio_api_key:
        return FishAudioTtsProvider(active_settings)
    return MockTtsProvider()


def _is_brain_configured(settings: Settings) -> bool:
    if settings.radio_agent_provider == "mock":
        return True
    if settings.radio_agent_provider == "anthropic":
        return bool(settings.anthropic_api_key)
    return bool(settings.openai_api_key)


def _build_fish_audio_tts_endpoint(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.lower().endswith("/v1/tts"):
        return normalized
    return f"{normalized}/v1/tts"


def _normalize_weather_context(
    device_context: DeviceContext | str | None,
) -> dict[str, str | float | None]:
    if isinstance(device_context, DeviceContext):
        city_hint = device_context.city_hint.strip() if device_context.city_hint else ""
        return {
            "city_hint": city_hint,
            "latitude": device_context.latitude,
            "longitude": device_context.longitude,
        }

    city_hint = device_context.strip() if isinstance(device_context, str) else ""
    return {
        "city_hint": city_hint,
        "latitude": None,
        "longitude": None,
    }
