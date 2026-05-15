# ClownfishStudio

ClownfishStudio 是一个 Agent-First 的 AI 电台项目。

它的目标不是做一个传统播放器，也不是“规则推荐 + AI 文案”的拼装系统，而是让 Agent 像电台导播一样，结合用户此刻的状态、天气、时间、听歌偏好和可播放内容，实时编排一档带有陪伴感的个人电台。

当前仓库的重点是：

- `server/`：统一的 FastAPI 后端，负责 Agent 调度、工具调用、会话状态和配置管理
- `desktop/`：Windows Electron 桌面端，作为前端壳层调用 `server/`
- `data/mock/`：本地 mock 数据，保证在没有完整真实 API 时也能跑通链路

## 当前状态

目前这套代码已经完成了一次从“桌面端本地拼逻辑”到“桌面端统一接入后端”的整理，核心链路已经收拢到 `server/`：

- 桌面端不再维护独立推荐后端
- Agent、节目生成、聊天、配置、provider 状态都由 `server/` 统一处理
- 打包后的 Windows 可执行程序会自动启动内置 FastAPI 后端
- 网易云、天气、TTS、Agent 配置都可以通过桌面端设置面板注入

## 项目结构

```text
ClownfishStudio/
├─ README.md
├─ AGENTS.md
├─ ARCHITECTURE.md
├─ DESIGN.md
├─ CLAUDE.md
├─ data/
│  └─ mock/
├─ desktop/
│  ├─ electron/
│  ├─ src/
│  ├─ package.json
│  └─ README.md
└─ server/
   ├─ app/
   │  ├─ agents/
   │  ├─ api/
   │  ├─ core/
   │  ├─ schemas/
   │  ├─ services/
   │  └─ tools/
   ├─ scripts/
   ├─ tests/
   ├─ pyproject.toml
   └─ .env.example
```

## 核心架构

整体架构是：

```text
Desktop UI -> Electron IPC -> FastAPI server -> tools/providers/agent -> program/session -> UI playback
```

职责划分如下：

- `desktop/`
  - 提供 Windows 客户端界面
  - 负责播放器 UI、聊天 UI、设置 UI
  - 通过 Electron IPC 调用本地后端
  - 打包时把 `server/` 一起带入可执行程序

- `server/app/api/`
  - 暴露统一 HTTP 接口
  - 接收桌面端请求
  - 返回节目、聊天回复、配置和运行状态

- `server/app/services/`
  - 编排主流程
  - 组合天气、记忆、历史、候选内容、TTS、会话状态
  - 驱动 Agent 生成节目和聊天结果

- `server/app/agents/`
  - `RadioAgentRuntime` 负责电台节目生成
  - `SongRequestAgent` 负责解析用户点歌意图
  - Agent 只能从真实工具返回的候选内容中选择，不允许凭空编造歌曲或链接

- `server/app/tools/`
  - 提供天气、历史、记忆、节目、网易云候选内容等工具
  - mock 工具从 `data/mock/*.json` 读取数据

## 当前支持的能力

### 1. 电台生成

后端可以基于以下上下文生成一档电台：

- 当前时间
- 城市与天气
- 用户输入的自由文本
- 历史节目和反馈
- mock 数据或网易云候选歌曲

对应接口：

- `POST /api/station/generate`
- `POST /api/programs/generate`

### 2. 对话式调台

用户可以通过聊天输入新的意图，例如：

- “我现在有点累”
- “想听安静一点”
- “帮我放周杰伦”
- “不要播客，来点下雨天的感觉”

后端会：

- 读取当前 session
- 解析用户需求
- 通过 Agent 或点歌解析器理解请求
- 搜索并重排可播放候选内容
- 返回新的节目和回复

对应接口：

- `POST /api/chat`

### 3. 网易云候选内容接入

当前后端已经预留并实现了网易云相关工具能力，支持通过 `NeteaseCloudMusicApi` 风格接口接入：

- 获取用户信息
- 读取歌单/推荐/最近听歌上下文
- 搜索歌曲
- 获取可播放 URL

相关配置：

- `NETEASE_API_BASE_URL`
- `NETEASE_COOKIE`
- `NETEASE_PLAYBACK_LEVEL`

### 4. Agent 与 Provider 配置

桌面端设置面板可以配置：

- Agent provider
  - `mock`
  - `openai`（OpenAI-compatible，包括 DeepSeek、OpenRouter、硅基流动、本地兼容网关等）
  - `anthropic`
- OpenWeather
- Fish Audio
- 网易云

桌面端会调用：

- `GET /api/config`
- `PUT /api/config`

### 5. Windows 桌面打包

桌面端使用 Electron 打包为 Windows portable exe。

当前打包产物路径：

```text
desktop/release/ClownfishStudio-0.1.0-windows-portable.exe
```

打包后的程序会自动尝试启动内置后端，默认监听：

```text
http://127.0.0.1:8000
```

## 主要接口

### 健康与状态

- `GET /health`
- `GET /api/runtime/status`
- `GET /api/agent/status`
- `GET /api/agent/music`

### 配置

- `GET /api/config`
- `PUT /api/config`

### 电台与聊天

- `POST /api/station/generate`
- `POST /api/chat`
- `GET /api/player/{user_id}/now`

### 兼容接口

- `POST /api/programs/generate`
- `POST /api/feedback`

## 本地开发

### 1. 启动后端

推荐使用 `uv`：

```powershell
cd server
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

检查服务：

```powershell
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/runtime/status
```

### 2. 启动桌面端

```powershell
cd desktop
npm install
npm run dev
```

开发模式下桌面端默认连接：

```text
http://127.0.0.1:8000
```

### 3. 打包 Windows 可执行程序

```powershell
cd desktop
npm run dist
```

产物位置：

```text
desktop/release/ClownfishStudio-0.1.0-windows-portable.exe
```

如果你是在某些终端环境里启动 exe，且环境变量 `ELECTRON_RUN_AS_NODE=1` 被错误继承，程序可能会直接退出。可以先执行：

```powershell
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
```

然后再启动 exe。

## 环境配置

参考：

- [server/.env.example](d:/workspace/vibe_coding/ClownfishStudio/server/.env.example)

主要配置项：

```env
RADIO_AGENT_PROVIDER=mock
RADIO_AGENT_MODEL=gpt-5.4

OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1

ANTHROPIC_API_KEY=
ANTHROPIC_BASE_URL=https://api.anthropic.com

TTS_PROVIDER=mock
FISH_AUDIO_API_KEY=
FISH_AUDIO_BASE_URL=https://api.fish.audio
FISH_AUDIO_VOICE_ID=

WEATHER_PROVIDER=mock
OPENWEATHER_API_KEY=
OPENWEATHER_BASE_URL=https://api.openweathermap.org

NETEASE_API_BASE_URL=
NETEASE_COOKIE=
NETEASE_PLAYBACK_LEVEL=standard
```

注意：

- 不要把真实 API Key、Cookie、`.env` 提交到 GitHub
- 当前 `.gitignore` 已经忽略了 `.env`、虚拟环境、缓存、数据库和打包产物

## 测试与校验

后端测试：

```powershell
cd server
uv run pytest -q
uv run ruff check .
```

桌面端构建校验：

```powershell
cd desktop
npm run build
```

当前已经验证通过的内容包括：

- `server`: `49 passed`
- `server`: `ruff check` passed
- `desktop`: `npm run build` passed
- `desktop`: `npm run dist` passed

## 当前限制

这版项目已经能跑通主链路，但还不是最终形态，当前限制主要有：

- 目前仓库重点是 `server/ + desktop/`，移动端不在当前提交范围内
- 网易云、天气、TTS 等真实服务依赖外部配置和可用网络
- UI 已经做成可用桌面端，但仍然还有持续打磨空间
- 推荐能力仍然受候选内容质量、Cookie 可用性和外部 API 稳定性影响

## 文档

- [ARCHITECTURE.md](d:/workspace/vibe_coding/ClownfishStudio/ARCHITECTURE.md)：架构说明
- [DESIGN.md](d:/workspace/vibe_coding/ClownfishStudio/DESIGN.md)：设计方向
- [desktop/README.md](d:/workspace/vibe_coding/ClownfishStudio/desktop/README.md)：桌面端说明
- [AGENTS.md](d:/workspace/vibe_coding/ClownfishStudio/AGENTS.md)：项目开发约束

## 一句话总结

ClownfishStudio 现在是一套“桌面端 + 本地后端 + Agent 编排”的 AI 电台原型：它不只是播歌，而是在尽量理解用户当下状态之后，为用户实时组织一档能听、能聊、能继续调整的个人电台。
