from fastapi import APIRouter

from app.schemas import DesktopConfigResponse, DesktopConfigUpdateRequest
from app.services.desktop_config import get_desktop_config, update_desktop_config

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("", response_model=DesktopConfigResponse)
def get_config() -> DesktopConfigResponse:
    return get_desktop_config()


@router.put("", response_model=DesktopConfigResponse)
def put_config(payload: DesktopConfigUpdateRequest) -> DesktopConfigResponse:
    return update_desktop_config(payload)
