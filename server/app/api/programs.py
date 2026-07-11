from fastapi import APIRouter

from app.agents import AgentOutputValidationError
from app.api.errors import agent_validation_error_response, netease_error_response
from app.schemas import GenerateProgramRequest, GenerateProgramResponse
from app.services.program_generation import ProgramGenerationService
from app.tools.netease_music_tool import NeteaseMusicToolError

router = APIRouter(prefix="/api/programs", tags=["programs"])


@router.post("/generate", response_model=GenerateProgramResponse)
def generate_program(request: GenerateProgramRequest) -> GenerateProgramResponse:
    service = ProgramGenerationService()

    try:
        return service.generate(request)
    except AgentOutputValidationError as exc:
        raise agent_validation_error_response(exc) from exc
    except NeteaseMusicToolError as exc:
        raise netease_error_response(exc) from exc
