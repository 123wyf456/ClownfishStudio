# ClownfishStudio 架构概览

ClownfishStudio 当前实现是一个桌面端 AI 电台：Electron + React 负责交互和播放，本地 FastAPI 后端负责 Agent 运行、工具编排、会话持久化和外部服务接入。

核心原则：

```text
Agent 是推荐大脑
工具提供事实和候选内容
服务层负责流程编排
客户端只负责交互、播放和本地桥接
```

## 分层总览

| 层级 | 主要目录 | 职责边界 |
| --- | --- | --- |
| 桌面 UI 层 | `desktop/src` | 展示 Radio、Player、Chat、Settings；采集时间、定位等设备上下文；发起生成、聊天、配置请求；不直接调用模型。 |
| Electron 桥接层 | `desktop/electron` | 创建窗口；生产环境启动本地后端；通过 `preload` 暴露 `window.clownfishApi`；管理 IPC、本地配置、音频缓存和桌面日志。 |
| FastAPI API 层 | `server/app/api` | 提供 `/api/station/generate`、`/api/chat`、`/api/config`、`/api/feedback`、`/health` 等接口；只做请求响应和 schema 边界。 |
| 服务编排层 | `server/app/services` | `StationOrchestrator` 管电台会话、问候、TTS、播放状态；`ProgramGenerationService` 汇总天气、时间、记忆、历史和候选内容。 |
| Agent 层 | `server/app/agents` | `RadioAgentRuntime` 调用 DeepSeek 或 mock 模型，生成节目、问候和聊天回复；`SongRequestPlanner` 理解用户点歌意图；输出必须通过 schema 校验。 |
| 工具与 Provider 层 | `server/app/tools`, `server/app/services/providers.py` | 读取天气、记忆、历史、网易云候选、播客候选、反馈、日历和 TTS；只返回事实和候选，不承担推荐主判断。 |
| 数据与外部服务层 | `server/app/db`, `data/mock`, runtime 目录 | SQLite 保存 session、chat history、current item；mock JSON 提供开发数据；外部接入 DeepSeek、OpenWeather、网易云音乐 API、Fish Audio。 |

> 目前仓库的可运行客户端是 `desktop/`。如果后续加入 `mobile/`，它应并列在客户端层，通过同一套后端 API 使用 Agent，不应直接访问模型或密钥。

## 核心链路

### 启动与生成电台

1. Electron 主进程启动窗口；打包环境下会启动本地 FastAPI 后端并检查 `/health`。
2. React UI 通过 `window.clownfishApi.generateStation()` 发起生成请求。
3. Electron 桥接层构造 `device_context`，包含本地时间、时区、语言、城市 hint、经纬度。
4. FastAPI `/api/station/generate` 调用 `StationOrchestrator`。
5. `ProgramGenerationService` 拉取天气、日历、用户记忆、历史记录、网易云和 mock 候选。
6. `RadioAgentRuntime` 将上下文和候选交给 Agent，由 Agent 生成 `RadioProgram`。
7. 后端校验 Agent 输出，确保节目项只能引用候选列表中的内容。
8. `StationOrchestrator` 再让 Agent 生成首句问候，调用 TTS，保存 session 到 SQLite。
9. Electron 桥接层规范化返回数据和音频 URL，UI 展示并播放。

### 聊天调整电台

1. 用户在 Chat 输入需求，例如“想听安静一点，不要播客”。
2. 桥接层调用 `/api/chat`，同时带上新的设备上下文。
3. 后端保存用户消息并读取 chat history。
4. `ProgramGenerationService` 使用用户消息作为新的 `free_text` 重新收集候选。
5. Agent 负责理解用户意图、重新编排节目，并生成简短回复。
6. 新 session、回复和历史记录写入 SQLite 后返回客户端。

### 播放状态

1. UI 使用 session 中的节目块和曲目队列播放。
2. `/api/player/{user_id}/now` 可返回当前 session、队列和 current item。
3. current item 持久化在 SQLite，避免进程重启后完全丢失播放上下文。

## 边界原则

- 客户端不保存模型密钥，不直接访问 DeepSeek、OpenAI、网易云、OpenWeather 或 Fish Audio。
- API 路由不堆业务逻辑，只调用 service。
- service 可以编排流程、做日志、做兜底和持久化，但不应把推荐写成固定规则系统。
- tools 和 providers 只提供事实、候选、缓存和外部能力。
- Agent 负责场景理解、推荐方向判断、节目结构、串场文案和聊天回复。
- Agent 不能编造歌曲、播客或播放链接，只能选择工具返回的候选内容。
- 所有 Agent 输出必须经过 Pydantic schema 校验。

## 关键文件索引

- `desktop/src/App.tsx`：桌面 UI 主入口。
- `desktop/electron/main.cjs`：窗口、后端进程、IPC 和日志。
- `desktop/electron/api-clients.cjs`：桌面端到 FastAPI 的桥接、设备上下文和音频缓存。
- `desktop/electron/preload.cjs`：向 renderer 暴露安全 API。
- `server/app/main.py`：FastAPI app、路由和静态音频目录。
- `server/app/api/station.py`：电台生成、聊天、播放状态接口。
- `server/app/services/station_orchestrator.py`：电台 session、问候、TTS、聊天流程。
- `server/app/services/program_generation.py`：上下文、候选收集和节目生成编排。
- `server/app/agents/runtime.py`：Agent Runtime、模型选择、输出校验。
- `server/app/agents/radio_agent.py`：模型客户端，包含 DeepSeek/OpenAI-compatible 调用和 mock 模式。
- `server/app/services/session_store.py`：SQLite session、chat history、current item 存储。
- `server/app/schemas/radio.py`：后端核心 Pydantic schema。
- `server/app/tools/*`：天气、记忆、历史、音乐、播客、反馈等工具。

## 架构图

根目录下的 `project-architecture.svg` 展示了当前项目每一层的功能边界和主要数据流。
