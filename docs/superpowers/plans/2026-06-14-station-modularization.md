# Station Modularization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Modularize the station orchestration flow without breaking existing desktop or API behavior.

**Architecture:** Keep `StationOrchestrator` as the public entrypoint while extracting chat planning, reply presentation, and playlist/session mutations into focused service modules. Preserve current route contracts and use tests to lock behavior before refactoring.

**Tech Stack:** Python, FastAPI, Pydantic, pytest, TypeScript, Electron, React

---

### Task 1: Lock Current Orchestrator Behavior With Service-Level Tests

**Files:**
- Create: `server/tests/test_station_service_modules.py`
- Modify: `server/tests/test_station_api.py`

- [ ] **Step 1: Write the failing service-level tests**

```python
from datetime import UTC, datetime

from app.schemas import ChatMessage, ChatRouterResult, DeviceContext, PlaylistItemSource, UserStateInput
from app.services.station_chat_planner import (
    build_initial_chat_user_state,
    build_router_request_text,
    fallback_chat_router_result,
)
from app.services.station_reply_presenter import compact_agent_reply, control_reply


def test_build_initial_chat_user_state_preserves_raw_user_text() -> None:
    router = ChatRouterResult(need_chat=True, need_music=True, emotion="tired")

    state = build_initial_chat_user_state(message="今天有点累，放慢一点", router=router)

    assert state["free_text"] == "今天有点累，放慢一点"
    assert "companionship" in state["needs"]
    assert "relax" in state["needs"]


def test_build_router_request_text_keeps_original_message_first() -> None:
    router = ChatRouterResult(need_music=True)

    text = build_router_request_text("来点中文歌", router=router)

    assert text.startswith("来点中文歌")


def test_control_reply_returns_chinese_copy_for_pause() -> None:
    assert control_reply(action="pause", message="暂停一下", has_session=True) == "好，先暂停。"


def test_compact_agent_reply_falls_back_to_short_chinese_reply() -> None:
    reply = compact_agent_reply("This is a very long English sentence.", fallback_message="陪我听会儿")

    assert reply in {"我在，先陪你听着。", "嗯，我们慢慢来。"}


def test_fallback_chat_router_result_only_marks_explicit_controls_as_control() -> None:
    router = fallback_chat_router_result("播放一点安静的歌")

    assert router.need_music is True
    assert router.need_control is False
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd server; pytest tests/test_station_service_modules.py -v`
Expected: FAIL with `ModuleNotFoundError` for the new service modules.

- [ ] **Step 3: Add minimal module shells**

```python
# server/app/services/station_chat_planner.py
from app.schemas import ChatRouterResult


def fallback_chat_router_result(message: str) -> ChatRouterResult:
    return ChatRouterResult(need_chat=True)


def build_router_request_text(message: str, router: ChatRouterResult) -> str:
    del router
    return message.strip()


def build_initial_chat_user_state(message: str, router: ChatRouterResult) -> dict[str, object]:
    del router
    return {
        "duration_minutes": 25,
        "needs": ["companionship"],
        "free_text": message.strip(),
    }
```

```python
# server/app/services/station_reply_presenter.py
def control_reply(*, action: str | None, message: str, has_session: bool) -> str:
    del action, message, has_session
    return "好。"


def compact_agent_reply(text: str, fallback_message: str) -> str:
    del text
    return fallback_message
```

- [ ] **Step 4: Run the tests again and observe assertion failures**

Run: `cd server; pytest tests/test_station_service_modules.py -v`
Expected: FAIL on assertions, confirming the tests now target behavior instead of missing files.

- [ ] **Step 5: Implement the real extracted behavior**

Implement the real logic by moving the current helper behavior from `station_orchestrator.py` into the new modules, then update the tests if needed only for exact existing behavior.

- [ ] **Step 6: Run the focused tests**

Run: `cd server; pytest tests/test_station_service_modules.py -v`
Expected: PASS

### Task 2: Extract Chat Planning And Reply Presentation From The Orchestrator

**Files:**
- Modify: `server/app/services/station_orchestrator.py`
- Create: `server/app/services/station_chat_planner.py`
- Create: `server/app/services/station_reply_presenter.py`

- [ ] **Step 1: Write the failing orchestrator integration test**

Add a test that patches planner / presenter helpers and proves `StationOrchestrator.chat()` delegates through them for a first-session chat flow.

- [ ] **Step 2: Run the targeted test and verify it fails**

Run: `cd server; pytest tests/test_station_api.py::test_station_chat_first_request_creates_single_session_without_seed_roundtrip -v`
Expected: FAIL once the new delegation assertions are added and not yet wired.

- [ ] **Step 3: Refactor `station_orchestrator.py` to use the new modules**

Move:
- router fallback helpers into `station_chat_planner.py`
- reply helpers into `station_reply_presenter.py`
- request text / initial user state builders into `station_chat_planner.py`

Keep public method behavior unchanged.

- [ ] **Step 4: Run the focused station API tests**

Run: `cd server; pytest tests/test_station_api.py -v`
Expected: PASS

### Task 3: Extract Playlist And Session Mutations

**Files:**
- Create: `server/app/services/station_session_mutations.py`
- Modify: `server/app/services/station_orchestrator.py`
- Modify: `server/tests/test_station_api.py`

- [ ] **Step 1: Write failing mutation tests**

Create tests for:
- retune playlist after current item
- refill writes inserted items and warnings
- advance preserves stale-request protection

- [ ] **Step 2: Run the mutation tests to verify they fail**

Run: `cd server; pytest tests/test_station_service_modules.py -v`
Expected: FAIL because mutation functions are not implemented yet.

- [ ] **Step 3: Move mutation logic into `station_session_mutations.py`**

Extract:
- initial playlist creation from generation
- retune session playlist application
- refill application
- advance session update helpers

The functions should accept explicit inputs and return updated `StationSessionState` or mutation payloads.

- [ ] **Step 4: Rewire orchestrator to call mutation helpers**

Keep persistence and runtime response assembly in orchestrator; move playlist/session mutation details out.

- [ ] **Step 5: Run focused tests**

Run: `cd server; pytest tests/test_station_service_modules.py tests/test_station_api.py -v`
Expected: PASS

### Task 4: Tighten Desktop API Typing And Response Mapping

**Files:**
- Modify: `desktop/src/api/types.ts`
- Modify: `desktop/src/api/desktopApi.ts`
- Modify: `desktop/src/radioData.ts`

- [ ] **Step 1: Write a failing TypeScript build expectation**

Introduce stricter typed response shapes for station/session/reply/runtime data. The existing code should fail type-checking or require explicit narrowing until the mapping is updated.

- [ ] **Step 2: Run the desktop build**

Run: `cd desktop; npm run build`
Expected: FAIL with type mismatches or implicit assumptions.

- [ ] **Step 3: Implement typed response models and safe mapping**

Add:
- backend response types for session, playlist, and reply
- mapping helpers that preserve current runtime behavior
- optional-field compatibility for future server fields

- [ ] **Step 4: Run the desktop build again**

Run: `cd desktop; npm run build`
Expected: PASS

### Task 5: Full Verification

**Files:**
- Modify: `docs/superpowers/specs/2026-06-14-station-modularization-design.md`
- Modify: `docs/superpowers/plans/2026-06-14-station-modularization.md`

- [ ] **Step 1: Run backend tests**

Run: `cd server; pytest`
Expected: PASS

- [ ] **Step 2: Run backend lint**

Run: `cd server; ruff check .`
Expected: PASS

- [ ] **Step 3: Format backend if needed**

Run: `cd server; ruff format .`
Expected: Either no changes needed or formatting applied cleanly.

- [ ] **Step 4: Re-run backend verification if formatting changed**

Run: `cd server; pytest && ruff check .`
Expected: PASS

- [ ] **Step 5: Run desktop build**

Run: `cd desktop; npm run build`
Expected: PASS

- [ ] **Step 6: Update the spec/plan if execution revealed a necessary change**

Document any small divergence from the original design in the saved files so the planning artifacts still match reality.

### Task 6: Follow-up Capabilities

**Files:**
- Modify: `server/app/schemas/radio.py`
- Modify: `server/app/services/station_orchestrator.py`
- Modify: `server/app/services/station_reply_presenter.py`
- Modify: `server/app/services/providers.py`
- Modify: `server/app/api/feedback.py`
- Modify: `desktop/electron/api-clients.cjs`
- Modify: `desktop/src/api/types.ts`
- Test: `server/tests/test_station_api.py`
- Test: `server/tests/test_station_service_modules.py`

- [ ] **Step 1: Add failing tests for reply metadata**

Add tests that prove station chat responses now expose structured metadata while preserving existing `reply.text`.

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `cd server; uv run pytest tests/test_station_api.py tests/test_station_service_modules.py -v`
Expected: FAIL because metadata fields do not exist yet.

- [ ] **Step 3: Implement reply metadata as optional schema fields**

Add a reply metadata schema and wire it through station chat responses while keeping current payloads compatible.

- [ ] **Step 4: Add failing tests for TTS interface behavior**

Add tests that verify a synthesized greeting/chat reply can populate `tts_text` and `tts_audio_url` when a provider is enabled, while degraded cases still return `None`.

- [ ] **Step 5: Run the TTS-focused tests to verify they fail**

Run: `cd server; uv run pytest tests/test_station_api.py tests/test_providers.py -v`
Expected: FAIL because station orchestration does not yet call the TTS service.

- [ ] **Step 6: Implement a station TTS helper service**

Create a small orchestration helper that uses `build_tts_provider()` after reply generation and writes `tts_text` / `tts_audio_url` back to the session.

- [ ] **Step 7: Add failing tests for control feedback writeback**

Add tests that verify `like`, `favorite`, and `skip` controls store feedback events and memory hints through the existing feedback tool path.

- [ ] **Step 8: Run the feedback tests to verify they fail**

Run: `cd server; uv run pytest tests/test_station_api.py tests/test_feedback_api.py -v`
Expected: FAIL because control actions are not yet persisted as feedback.

- [ ] **Step 9: Implement control feedback persistence**

Wire selected control actions into the feedback tool helpers without changing the explicit player-control behavior.

- [ ] **Step 10: Add failing tests for runtime events**

Add tests that verify chat/generation/control actions emit lightweight runtime event entries attached to the session.

- [ ] **Step 11: Run the runtime event tests to verify they fail**

Run: `cd server; uv run pytest tests/test_station_api.py tests/test_station_service_modules.py -v`
Expected: FAIL because runtime events are not yet modeled.

- [ ] **Step 12: Implement runtime event support and desktop mapping**

Add optional session event records, expose them through API responses, and map them compatibly in the desktop bridge for future UI use.

- [ ] **Step 13: Re-run full verification**

Run:
- `cd server; uv run pytest`
- `cd server; uv run ruff check .`
- `cd desktop; npm run build`

Expected: PASS

### Execution Notes

本计划现已完成，实际落地结果与原 follow-up 目标保持一致：

- 已增加 reply metadata，并通过 station chat API 暴露
- 已增加独立 TTS service，并在生成 / 对话回复后回写 session
- 已把 `like` / `favorite` / `skip` 接入 feedback + memory hint 链路
- 已增加 session runtime events，并兼容映射到桌面端 bridge

验证结果：

- `cd server && uv run pytest` -> 104 passed
- `cd server && uv run ruff check .` -> passed
- `cd server && uv run ruff format .` -> applied cleanly
- `cd desktop && npm run build` -> passed
