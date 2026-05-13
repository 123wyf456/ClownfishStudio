from fastapi import APIRouter, HTTPException

from app.agents import AgentOutputValidationError
from app.schemas import GenerateProgramRequest, GenerateProgramResponse
from app.services.program_generation import ProgramGenerationService

router = APIRouter(prefix="/api/programs", tags=["programs"])


@router.post("/generate", response_model=GenerateProgramResponse)
def generate_program(request: GenerateProgramRequest) -> GenerateProgramResponse:
    service = ProgramGenerationService()

    try:
        return service.generate(request)
    except AgentOutputValidationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
