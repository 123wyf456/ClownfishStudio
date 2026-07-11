from fastapi import HTTPException

from app.agents import AgentOutputValidationError
from app.tools.netease_music_tool import NeteaseMusicToolError


def netease_error_response(exc: NeteaseMusicToolError) -> HTTPException:
    raw_error = str(exc).strip()
    lowered = raw_error.lower()

    if "netease_api_base_url is not configured" in lowered:
        message = "网易云音乐服务未配置：请在设置里填写网易云服务地址。"
    elif (
        "winerror 10061" in lowered or "connection refused" in lowered or "urlopen error" in lowered
    ):
        message = (
            "网易云音乐服务连接失败：请确认 NeteaseCloudMusicApi 已启动，"
            "并检查设置里的网易云服务地址。"
        )
    elif "/song/url" in lowered:
        message = "网易云音乐播放链接获取失败：请检查账号 Cookie 和播放音质配置。"
    elif "/login/status" in lowered:
        message = "网易云音乐登录状态读取失败：请检查网易云 Cookie。"
    elif "/search" in lowered:
        message = "网易云音乐搜索失败：请检查网易云服务状态和搜索接口。"
    else:
        message = "网易云音乐服务请求失败。"

    detail = f"{message} 原始错误：{raw_error}" if raw_error else message
    return HTTPException(status_code=503, detail=detail)


def agent_validation_error_response(exc: AgentOutputValidationError) -> HTTPException:
    raw_error = str(exc).strip()
    if "requires at least one candidate item" in raw_error:
        detail = f"音乐服务没有返回任何可播放内容，Agent 无法生成电台。 原始错误：{raw_error}"
        return HTTPException(status_code=422, detail=detail)

    return HTTPException(status_code=502, detail=raw_error)
