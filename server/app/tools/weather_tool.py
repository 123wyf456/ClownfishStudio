from app.tools.mock_data import read_mock_json

WeatherData = dict[str, str | int | float | bool | None]


def get_weather(city_hint: str | None) -> WeatherData:
    data = read_mock_json("weather.json")
    default_weather = data["default"]
    cities = data["cities"]

    if not isinstance(default_weather, dict) or not isinstance(cities, dict):
        raise ValueError("weather mock data is malformed")

    if not city_hint:
        return dict(default_weather)

    city_weather = cities.get(city_hint)
    if not isinstance(city_weather, dict):
        fallback = dict(default_weather)
        fallback["city"] = city_hint
        return fallback

    return dict(city_weather)
