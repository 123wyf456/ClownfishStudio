from __future__ import annotations

from app.schemas import ChatRouterResult


def fallback_chat_router_result(message: str) -> ChatRouterResult:
    text = message.strip().lower()
    if not text:
        return ChatRouterResult(emotion="neutral", need_chat=True, confidence=0.4)

    control_action = _detect_control_action(text)
    if control_action is not None:
        return ChatRouterResult(
            emotion="neutral",
            need_control=True,
            control_action=control_action,
            confidence=0.85,
        )

    return ChatRouterResult(emotion="neutral", need_chat=True, confidence=0.55)


def build_router_request_text(message: str, router: ChatRouterResult) -> str:
    constraints = router.music_constraints
    fragments = [constraints.raw_query or message.strip()]
    if constraints.artists:
        fragments.append("artists: " + ", ".join(constraints.artists))
    if constraints.tracks:
        fragments.append("tracks: " + ", ".join(constraints.tracks))
    if constraints.genres:
        fragments.append("genres: " + ", ".join(constraints.genres))
    if constraints.languages:
        fragments.append("languages: " + ", ".join(constraints.languages))
    if constraints.scenes:
        fragments.append("scenes: " + ", ".join(constraints.scenes))
    if constraints.mood:
        fragments.append(f"mood: {constraints.mood}")
    if constraints.energy:
        fragments.append(f"energy: {constraints.energy}")
    if constraints.avoid:
        fragments.append("avoid: " + ", ".join(constraints.avoid))
    return "; ".join(fragment for fragment in fragments if fragment)


def build_initial_chat_user_state(message: str, router: ChatRouterResult) -> dict[str, object]:
    needs = ["companionship"]
    if router.emotion in {"tired", "anxious", "calm"}:
        needs.append("relax")
    if router.need_music and router.emotion not in {"tired", "anxious", "calm"}:
        needs.append("discover")
    return {
        "duration_minutes": 25,
        "needs": list(dict.fromkeys(needs)),
        "free_text": build_router_request_text(message, router),
    }


def router_has_content(router: ChatRouterResult) -> bool:
    return router.need_chat or router.need_music or router.need_info


def router_log_label(router: ChatRouterResult) -> str:
    parts: list[str] = []
    if router.need_control:
        parts.append(f"control:{router.control_action or 'unknown'}")
    if router.need_chat:
        parts.append("chat")
    if router.need_music:
        parts.append("music")
    if router.need_info:
        parts.append("info")
    return "+".join(parts) if parts else "none"


def chat_regeneration_candidate_limit(
    *,
    message: str,
    router: ChatRouterResult,
) -> int:
    if requires_real_music_candidates(message=message, router=router):
        return 8
    return 10


def requires_real_music_candidates(
    *,
    message: str,
    router: ChatRouterResult,
) -> bool:
    constraints = router.music_constraints
    if constraints.artists or constraints.tracks:
        return True
    return _contains_any(
        message.strip().lower(),
        [
            "来一首",
            "给我来一首",
            "放点",
            "想听",
            "listen to",
            "play ",
            "song",
            "artist",
        ],
    )


def _detect_control_action(text: str) -> str | None:
    if _contains_any(text, ["暂停", "pause", "停一下", "先停"]):
        return "pause"
    if _contains_any(text, ["继续播放", "继续放", "播放吧", "resume", "continue"]):
        return "play"
    if _contains_any(text, ["下一首", "切歌", "跳过", "next", "skip"]):
        return "skip"
    if _contains_any(text, ["上一首", "previous", "back"]):
        return "previous"
    if _contains_any(text, ["停止播放", "stop"]):
        return "stop"
    if _contains_any(text, ["收藏", "favorite", "collect"]):
        return "favorite"
    if _contains_any(text, ["喜欢这首", "like this", "i like this"]):
        return "like"
    return None


def _contains_any(text: str, values: list[str]) -> bool:
    return any(value in text for value in values)
