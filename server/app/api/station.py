from fastapi import APIRouter

from app.schemas import (
    GenerateProgramRequest,
    PlayerNowResponse,
    RuntimeStatus,
    StationChatRequest,
    StationChatResponse,
    StationGenerateResponse,
)
from app.services.station_orchestrator import StationOrchestrator

router = APIRouter(prefix="/api", tags=["station"])


@router.post("/station/generate", response_model=StationGenerateResponse)
def generate_station(request: GenerateProgramRequest) -> StationGenerateResponse:
    orchestrator = StationOrchestrator()
    return orchestrator.generate_station(request)


@router.post("/chat", response_model=StationChatResponse)
def chat(request: StationChatRequest) -> StationChatResponse:
    orchestrator = StationOrchestrator()
    return orchestrator.chat(request)


@router.get("/player/{user_id}/now", response_model=PlayerNowResponse)
def player_now(user_id: str) -> PlayerNowResponse:
    orchestrator = StationOrchestrator()
    return orchestrator.now_playing(user_id)


@router.get("/runtime/status", response_model=RuntimeStatus)
def runtime_status() -> RuntimeStatus:
    orchestrator = StationOrchestrator()
    return orchestrator.runtime_status()
