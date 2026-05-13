# ClownfishStudio

ClownfishStudio 是一个 Agent-First 的个人 AI 电台。

这一版仓库已经重构为你描述的本地编排架构：

- 移动端负责 `Radio / Player / Chat` 三个核心界面。
- 本地 FastAPI 服务器负责任务调度、上下文组装、工具调用和状态输出。
- Agent 作为“大脑”，决定节目结构、串场文案和候选内容排序。
- 音乐、天气、日程、语音都通过独立 provider 边界接入，方便后续替换成真实 API。

## 当前架构

核心目录：

```text
ClownfishStudio/
├─ mobile/
│  ├─ app/App.tsx
│  ├─ features/radio/types.ts
│  ├─ services/
│  └─ store/radioStore.ts
├─ server/
│  ├─ app/api/
│  ├─ app/agents/
│  ├─ app/core/
│  ├─ app/schemas/
│  ├─ app/services/
│  └─ app/tools/
├─ data/mock/
└─ ARCHITECTURE.md
```

关键服务分层：

- `server/app/services/program_generation.py`
  负责节目生成主流程，聚合天气、记忆、历史、候选内容，调用 `RadioAgentRuntime`。
- `server/app/services/station_orchestrator.py`
  负责“本地电台调度器”，输出电台 session、聊天响应、播放器状态。
- `server/app/services/providers.py`
  定义 `brain / tts / calendar / weather / music` 的 provider 边界与运行时状态。
- `mobile/app/App.tsx`
  当前移动端入口，已经按 `Radio / Player / Chat` 三屏重组。

## 后端接口

新主接口：

- `POST /api/station/generate`
  生成一档完整的电台 session。
- `POST /api/chat`
  和电台对话，返回 Agent 回复与当前 session。
- `GET /api/player/{user_id}/now`
  获取当前播放状态和队列。
- `GET /api/runtime/status`
  查看本地调度器当前 provider 状态。

保留的兼容接口：

- `POST /api/programs/generate`
- `POST /api/feedback`
- `GET /api/agent/status`
- `GET /health`

## 运行方式

### 1. 启动后端

推荐在 WSL 或本机 Python 环境中运行：

```powershell
cd server
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

检查：

```powershell
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/runtime/status
```

### 2. 启动移动端

```powershell
cd mobile
npm install
copy .env.example .env
```

Android 模拟器：

```text
EXPO_PUBLIC_API_BASE_URL=http://10.0.2.2:8000
```

iOS 模拟器通常可用：

```text
EXPO_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

启动：

```powershell
npm.cmd run android
# 或
npm.cmd run ios
```

### 3. 启动网易云 API

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\server\scripts\start_netease_api.ps1
```

如果后端运行在 WSL，先试：

```text
NETEASE_API_BASE_URL=http://localhost:3000
```

如果你的 WSL 不能直接访问 localhost，再改成对应桥接地址。  
如果后端直接运行在 Windows：

```text
NETEASE_API_BASE_URL=http://localhost:3000
```

## Provider 接线规划

当前已经把真实接线点预留好了：

- DeepSeek：`RADIO_AGENT_PROVIDER=deepseek`
- Fish Audio：`TTS_PROVIDER=fish_audio`
- 飞书日程：`CALENDAR_PROVIDER=feishu`
- OpenWeather：`WEATHER_PROVIDER=openweather`
- 网易云：`NETEASE_API_BASE_URL`

配置模板见 `server/.env.example`。

建议接线顺序：

1. 先接 DeepSeek，验证节目生成链路。
2. 再接 OpenWeather 和飞书，把上下文补全。
3. 再接 Fish Audio，让串场文案具备语音输出。
4. 最后稳定网易云播放和 cookie/播放地址策略。

## 验证

后端：

```powershell
wsl -d Ubuntu22 sh -lc "cd /mnt/d/workspace/vibe_coding/ClownfishStudio/server && python3 -m pytest -q"
```

移动端：

```powershell
cd mobile
npm.cmd run lint
npm.cmd run typecheck
```

本次重构完成后的验证结果：

- `pytest`: `46 passed`
- `npm run lint`: passed
- `npm run typecheck`: passed

## 下一步

下一步最适合直接做的不是继续改架构，而是开始接真实 provider。

你后续把这些信息给我，我们就可以继续接：

- DeepSeek API key / model / base URL
- Fish Audio key / voice id
- 飞书 app id / secret / calendar id
- OpenWeather key
- 网易云 cookie 与可用接口策略
