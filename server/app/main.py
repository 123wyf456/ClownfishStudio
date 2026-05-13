from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.agent import router as agent_router
from app.api.config import router as config_router
from app.api.feedback import router as feedback_router
from app.api.health import router as health_router
from app.api.programs import router as programs_router
from app.api.station import router as station_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.services.providers import AUDIO_OUTPUT_DIR


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title=settings.app_name)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    AUDIO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/generated-audio", StaticFiles(directory=AUDIO_OUTPUT_DIR), name="generated-audio")
    app.include_router(health_router)
    app.include_router(agent_router)
    app.include_router(config_router)
    app.include_router(programs_router)
    app.include_router(feedback_router)
    app.include_router(station_router)
    return app


app = create_app()
