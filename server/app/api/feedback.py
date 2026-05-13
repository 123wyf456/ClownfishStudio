from fastapi import APIRouter

from app.schemas import FeedbackEvent, FeedbackResponse
from app.tools import build_memory_update_hint, save_feedback, save_memory_update_hint

router = APIRouter(prefix="/api", tags=["feedback"])


@router.post("/feedback", response_model=FeedbackResponse)
def create_feedback(feedback: FeedbackEvent) -> FeedbackResponse:
    saved_feedback = save_feedback(feedback)
    memory_update_hint = save_memory_update_hint(build_memory_update_hint(saved_feedback))

    return FeedbackResponse(
        feedback=saved_feedback,
        memory_update_hint=memory_update_hint,
    )
