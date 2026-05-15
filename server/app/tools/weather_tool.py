from app.schemas import DeviceContext
from app.tools.mock_data import read_mock_json

WeatherData = dict[str, str | int | float | bool | None]


def get_weather(city_hint: DeviceContext | str | None) -> WeatherData:
    data = read_mock_json("weather.json")
    default_weather = data["default"]
    cities = data["cities"]

    if not isinstance(default_weather, dict) or not isinstance(cities, dict):
        raise ValueError("weather mock data is malformed")

    normalized_city = _normalize_city_hint(city_hint)
    if not normalized_city:
        return dict(default_weather)

    city_weather = cities.get(normalized_city)
    if not isinstance(city_weather, dict):
        fallback = dict(default_weather)
        fallback["city"] = normalized_city
        return fallback

    return dict(city_weather)


def _normalize_city_hint(city_hint: DeviceContext | str | None) -> str:
    if isinstance(city_hint, DeviceContext):
        return city_hint.city_hint.strip() if city_hint.city_hint else ""
    return city_hint.strip() if isinstance(city_hint, str) else ""
