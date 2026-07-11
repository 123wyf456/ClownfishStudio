from __future__ import annotations

import hashlib
import re

from app.schemas import ChatRouterResult, ReplyMetadata


def control_reply(
    *,
    action: str | None,
    message: str,
    has_session: bool,
) -> str:
    use_chinese = prefer_chinese(message)
    if not has_session:
        if use_chinese:
            return "电台还没开始，我先给你接上。"
        return "The station was not running; I started it."

    if use_chinese:
        replies = {
            "play": "好，继续播放。",
            "pause": "好，先暂停。",
            "next": "好，切到下一首。",
            "skip": "好，跳过这首。",
            "previous": "好，回到上一首。",
            "stop": "好，先停在这里。",
            "like": "好，我记下你喜欢这首。",
            "favorite": "好，我帮你记下这首。",
        }
        return replies.get(action or "", "好。")

    replies = {
        "play": "Okay, resuming.",
        "pause": "Okay, paused.",
        "next": "Okay, next track.",
        "skip": "Okay, skipping this.",
        "previous": "Okay, back one track.",
        "stop": "Okay, stopping here.",
        "like": "Okay, I noted that you like this.",
        "favorite": "Okay, I marked this one.",
    }
    return replies.get(action or "", "Okay.")


def compact_agent_reply(text: str, fallback_message: str) -> str:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return fallback_chat_reply(
            message=fallback_message,
            router=ChatRouterResult(need_chat=True),
        )
    if prefer_chinese(fallback_message) and not prefer_chinese(normalized):
        return fallback_chat_reply(
            message=fallback_message,
            router=ChatRouterResult(need_chat=True),
        )

    first_sentence = re.split(r"(?<=[。！？.!?])\s*", normalized, maxsplit=1)[0].strip()
    if first_sentence:
        normalized = first_sentence

    prefers_chinese = prefer_chinese(fallback_message) or prefer_chinese(normalized)
    limit = 36 if prefers_chinese else 96
    if len(normalized) <= limit:
        return normalized
    suffix = "。" if prefers_chinese else "."
    return normalized[:limit].rstrip("，。！？,.!? ") + suffix


def fallback_chat_reply(message: str, router: ChatRouterResult) -> str:
    reply_kind = _router_reply_kind(router)
    if prefer_chinese(message):
        variants = {
            "control": ["好。", "收到。"],
            "info": ["我看一下这首的信息。", "好，我给你说清楚一点。"],
            "music": ["好，我按这个方向找歌。", "这个口味我接住了。"],
            "chat": ["我在，先陪你听着。", "嗯，我们慢慢来。"],
        }
    else:
        variants = {
            "control": ["Okay.", "Done."],
            "info": ["I will check this track.", "Let me make that clear."],
            "music": ["Got it, I will look that way.", "I hear the taste; next set follows."],
            "chat": ["I am here; we can keep listening.", "Yeah, let us take it slowly."],
        }
    return _stable_variant(variants.get(reply_kind) or variants["chat"], f"{reply_kind}:{message}")


def build_reply_metadata(
    *,
    reply_kind: str,
    reply_source: str,
    playlist_changed: bool,
    event_id: str | None,
) -> ReplyMetadata:
    return ReplyMetadata(
        reply_kind=reply_kind,
        reply_source=reply_source,
        playlist_changed=playlist_changed,
        event_id=event_id,
    )


def prefer_chinese(value: str) -> bool:
    chinese_count = len(re.findall(r"[\u4e00-\u9fff]", value))
    ascii_word_count = len(re.findall(r"[A-Za-z]{2,}", value))
    return chinese_count > 0 and chinese_count >= ascii_word_count


def _stable_variant(values: list[str], seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()
    return values[int(digest[:8], 16) % len(values)]


def _router_reply_kind(router: ChatRouterResult) -> str:
    if router.need_control:
        return "control"
    if router.need_info and not router.need_music:
        return "info"
    if router.need_music:
        return "music"
    return "chat"
