import os

from app.core.config import get_settings


def pytest_configure() -> None:
    os.environ["NETEASE_API_BASE_URL"] = ""
    os.environ["OPENAI_API_KEY"] = ""
    os.environ["ANTHROPIC_API_KEY"] = ""
    os.environ["RADIO_AGENT_PROVIDER"] = "mock"
    os.environ["RADIO_AGENT_MODEL"] = "test-model"
    os.environ["TTS_PROVIDER"] = "mock"
    os.environ["CALENDAR_PROVIDER"] = "mock"
    os.environ["WEATHER_PROVIDER"] = "mock"
    get_settings.cache_clear()


def pytest_runtest_setup() -> None:
    from app.services import session_store, station_orchestrator
    from app.tools import feedback_tool, history_tool, program_tool

    feedback_tool._SAVED_FEEDBACK_EVENTS = None
    feedback_tool._SAVED_MEMORY_UPDATE_HINTS = None
    history_tool._SAVED_HISTORY_EVENTS = None
    program_tool._SAVED_PROGRAMS = None
    session_store.clear_station_session_store()
    station_orchestrator._USER_GENERATION_LOCKS.clear()
    get_settings.cache_clear()
