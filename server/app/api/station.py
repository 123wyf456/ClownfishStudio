from fastapi import APIRouter, HTTPException

from app.agents import AgentOutputValidationError
from app.api.errors import agent_validation_error_response, netease_error_response
from app.schemas import (
    GenerateProgramRequest,
    PlayerAdvanceRequest,
    PlayerAdvanceResponse,
    PlayerNowResponse,
    RuntimeStatus,
    StationChatRequest,
    StationChatResponse,
    StationGenerateResponse,
)
from app.services.station_orchestrator import NoSuitableSongError, StationOrchestrator
from app.tools.netease_music_tool import NeteaseMusicToolError

router = APIRouter(prefix="/api", tags=["station"])


@router.post("/station/generate", response_model=StationGenerateResponse)
def generate_station(request: GenerateProgramRequest) -> StationGenerateResponse:
    orchestrator = StationOrchestrator()
    try:
        return orchestrator.generate_station(request)
    except NeteaseMusicToolError as exc:
        raise netease_error_response(exc) from exc
    except AgentOutputValidationError as exc:
        raise agent_validation_error_response(exc) from exc


@router.post("/chat", response_model=StationChatResponse)
def chat(request: StationChatRequest) -> StationChatResponse:
    orchestrator = StationOrchestrator()
    try:
        return orchestrator.chat(request)
    except NoSuitableSongError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except NeteaseMusicToolError as exc:
        raise netease_error_response(exc) from exc
    except AgentOutputValidationError as exc:
        raise agent_validation_error_response(exc) from exc


@router.get("/player/{user_id}/now", response_model=PlayerNowResponse)
def player_now(user_id: str) -> PlayerNowResponse:
    orchestrator = StationOrchestrator()
    return orchestrator.now_playing(user_id)


@router.post("/player/{user_id}/advance", response_model=PlayerAdvanceResponse)
def player_advance(user_id: str, request: PlayerAdvanceRequest) -> PlayerAdvanceResponse:
    orchestrator = StationOrchestrator()
    return orchestrator.advance_player(user_id=user_id, request=request)


@router.post("/player/{user_id}/refill", response_model=PlayerAdvanceResponse)
def player_refill(user_id: str) -> PlayerAdvanceResponse:
    orchestrator = StationOrchestrator()
    try:
        return orchestrator.refill_player(user_id=user_id)
    except NeteaseMusicToolError as exc:
        raise netease_error_response(exc) from exc
    except AgentOutputValidationError as exc:
        raise agent_validation_error_response(exc) from exc


@router.get("/runtime/status", response_model=RuntimeStatus)
def runtime_status() -> RuntimeStatus:
    orchestrator = StationOrchestrator()
    return orchestrator.runtime_status()
