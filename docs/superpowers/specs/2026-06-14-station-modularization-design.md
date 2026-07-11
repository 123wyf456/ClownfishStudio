# ClownfishStudio Station Modularization Design

## Goal

在不破坏当前 `desktop + FastAPI` 使用方式的前提下，把电台主流程从“单文件大编排器”收束为更清晰的 Agent-first 模块边界，同时为后续能力扩展预留接口。

## Current State

当前站点主流程高度集中在 `server/app/services/station_orchestrator.py`：

- 初始电台生成、聊天路由、控制命令、retune、refill、reply fallback 都混在同一个类中
- 一部分“边界型 fallback”是合理的，但它们与状态变更、reply 压缩、playlist 变更逻辑耦合在一起
- 桌面端依赖 `desktop/electron/api-clients.cjs` 把后端 `session / playlist / reply` 映射成前端 `Station`
- 当前 API 已经可用，不能通过大幅重写破坏现有路由和桌面端消费方式

这与 `AGENTS.md` 中的核心要求存在张力：

- 服务层应该协调，而不应过度替模型做理解
- 模型要直接看到用户原话、近期聊天、上下文和候选内容
- 后端可以约束结构和事实，不能继续朝“规则系统 + LLM 包装层”演化

## Design Principles

本次改造遵循以下原则：

1. 保持现有 API 路径与基本响应形状兼容
2. 优先拆职责，不做无关重构
3. fallback 保留在边界层，不让它重新主导推荐理解
4. 状态变更、文本呈现、聊天 planning 分离
5. 后续扩展通过新增模块和增量 schema 字段接入，而不是再次把逻辑塞回 orchestrator

## Recommended Approach

采用“分层模块化改造”：

- `StationOrchestrator` 继续作为统一入口，但只负责主流程编排
- 抽出聊天 planning 模块，统一封装 Agent router 与最小 fallback
- 抽出 reply presenter 模块，统一压缩 greeting / reply / control text
- 抽出 session mutation 模块，统一处理 retune / refill / advance 的 session/playlist 更新
- 维持 `ProgramGenerationService` 和 `RadioAgentRuntime` 的 Agent-first 主链路，不用后端规则替代模型理解
- 桌面端保持兼容消费，但补齐真实类型和映射边界

## File Boundaries

### Server

#### `server/app/services/station_orchestrator.py`

保留公开入口：

- `generate_station`
- `chat`
- `now_playing`
- `advance_player`
- `refill_player`

但删除内部大段文本逻辑与 mutation 细节，改为调用模块函数。

#### `server/app/services/station_chat_planner.py`

职责：

- 封装 `runtime.plan_chat_turn`
- 提供最小 fallback router
- 负责判断“是否只有 control 而无内容请求”
- 负责构建 chat round 使用的初始 `user_state` 与 retune request text

这层只做“turn planning”，不直接改 session。

#### `server/app/services/station_reply_presenter.py`

职责：

- 统一生成和压缩 greeting / chat reply / control reply / fallback reply
- 保留当前中英文压缩策略
- 为后续 richer reply metadata 预留接口

后续若要增加 `reply_kind`、`reply_source`、`playlist_changed` 等元信息，从这里扩展最自然。

#### `server/app/services/station_session_mutations.py`

职责：

- 根据 generation 结果 retune playlist
- 应用 advance / refill 对 playlist 的状态变更
- 记录 playlist events
- 统一构造保存后的 `StationSessionState`

这层尽量纯函数化，减少 UI 文字和 runtime 调用。

### Desktop

#### `desktop/electron/api-clients.cjs`

继续作为桌面兼容适配层：

- 映射后端 session/playlist 到前端 `Station`
- 优先消费现有字段
- 对未来新增字段采用“读到即用，读不到不报错”的策略

#### `desktop/src/api/types.ts`

补齐服务端返回结构对应的类型定义，让桌面端不再依赖过于宽泛的 `unknown -> Station` 假设。

## Data Flow

### Initial Generate

1. Desktop 调用 `/api/station/generate`
2. `StationOrchestrator` 调用 `ProgramGenerationService`
3. Agent 直接接收原始 `user_state.free_text`、chat history、weather、memory、候选
4. Orchestrator 通过 reply presenter 生成 greeting
5. mutation 模块从候选中初始化 playlist
6. session 保存后返回给桌面端

### Chat Turn

1. 读取当前 session 与 chat history
2. planner 调用 Agent router；失败时走最小 fallback
3. 若是显式 control，则 mutation 模块处理 playlist 状态变更
4. 若需要 retune，则继续生成候选并更新 playlist
5. reply presenter 统一产出最终回复
6. 返回更新后的 session

### Player Advance / Refill

1. advance 只做推进，不同步生成 refill 候选
2. refill 单独调用 generation，并由 mutation 模块写回 playlist
3. 桌面端继续保留后台 refill 行为

## Compatibility Strategy

兼容策略如下：

- 不修改现有路由：
  - `/api/station/generate`
  - `/api/chat`
  - `/api/player/{user_id}/now`
  - `/api/player/{user_id}/advance`
  - `/api/player/{user_id}/refill`
- 不删除现有关键字段：
  - `session`
  - `reply`
  - `session.greeting`
  - `session.playlist`
  - `session.warnings`
- 桌面端仍通过现有 `normalizeStationResponse` 消费数据
- 可以新增增量字段，但所有新增字段都必须是可选兼容的

## Testing Strategy

优先用现有测试兜住行为：

- `server/tests/test_station_api.py`
  验证 generate/chat/advance/refill 兼容行为不变
- 新增服务层测试
  验证 planner、reply presenter、session mutations 的独立行为
- `server/tests/test_program_generation_service.py`
  确保候选生成链路没有回退成强规则推荐

桌面端至少保证：

- 类型编译通过
- `normalizeStationResponse` 仍能兼容当前后端返回

## Implementation Scope For This Round

本轮必须落地：

- 拆出 `station_chat_planner.py`
- 拆出 `station_reply_presenter.py`
- 拆出 `station_session_mutations.py`
- 让 `station_orchestrator.py` 显著瘦身并委托这些模块
- 为桌面端补齐更真实的 API 类型
- 补对应测试

本轮只预留接口、不强行实现：

- TTS 真实生成与缓存
- 更细的 reply metadata
- 更丰富的用户反馈回写
- 统一 event telemetry

## Current Follow-up Status

本轮已完成原计划中的 follow-up 能力接入：

1. `Reply Metadata`
   聊天返回已经带有可选 `reply_kind`、`reply_source`、`playlist_changed`、`event_id`。
2. `TTS Pipeline`
   已增加独立 `station_tts.py` 编排层，在 greeting / chat reply 后写回 `tts_text` 与 `tts_audio_url`。
3. `User Feedback Loop`
   `like` / `favorite` / `skip` 已经通过独立 feedback service 写回 feedback event 与 memory hint。
4. `Runtime Events`
   session 已增加轻量 `events` 字段，支持 `session_created`、`reply_generated`、`playlist_retuned`、`playback_control`、`feedback_recorded`。

## Remaining Roadmap

后续建议继续推进的方向：

1. `Event Consumers`
   把 session events 接到桌面端 UI，用于 timeline、debug 面板或更细的状态提示。
2. `TTS Delivery`
   继续完善真实语音缓存、播放切换与失败降级策略，但保持当前字段兼容。
3. `Feedback Semantics`
   细化 `favorite`、`want_more_like_this`、`less_like_this` 等反馈语义映射。
4. `Event Persistence / Telemetry`
   如果后续要做更强分析或调试，可把 session events 再持久化到独立事件流，而不是只挂在 session snapshot 上。

## Risks

- 现有测试覆盖 service 内部行为不够细，拆分时容易出现回归
- 桌面端映射是 CommonJS 文件，类型保护较弱，必须通过兼容式调整避免引入显示层错误
- 当前仓库存在用户未提交修改，因此本轮必须避免回退或覆盖无关变更

## Success Criteria

- `station_orchestrator.py` 不再承载主要 fallback 文本逻辑与 mutation 细节
- 聊天 planning、reply、playlist mutation 都有清晰模块
- API 路由与桌面端基本用法保持不变
- 后端仍然以 Agent-first 方式理解用户，而不是新增更重的硬编码路由
- 测试通过，桌面端 build 通过
