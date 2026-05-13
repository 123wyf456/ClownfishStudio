# ClownfishStudio Architecture

## 1. 目标

ClownfishStudio 不是传统播放器，也不是“规则推荐 + LLM 文案”。

它的目标是：

> 让本地 Agent 像电台导演一样，基于用户此刻的状态、天气、日程和可播放内容，实时编排一档个人电台节目。

## 2. 分层

### 交互层

`mobile/`

三个核心界面：

- `Radio`
  输入此刻状态，发起电台生成。
- `Player`
  展示当前内容、队列、反馈按钮和串场文案。
- `Chat`
  和电台对话，影响后续重新生成与节目氛围。

### 本地调度层

`server/app/api` + `server/app/services`

职责：

- 采集移动端请求
- 汇总设备上下文
- 调用天气、日程、音乐、记忆、历史工具
- 调用 Agent 大脑生成节目
- 维护 `session / chat / now playing` 状态
- 暴露统一 HTTP 接口给前端

### Agent 大脑层

`server/app/agents`

职责：

- 组装 prompt
- 调用模型
- 要求模型只从候选内容中选择
- 对结构化输出做 schema 校验
- 拒绝编造歌曲、播客和播放地址

### Provider / Tool 层

`server/app/services/providers.py`
`server/app/tools/*`

职责：

- `brain`: DeepSeek / mock
- `tts`: Fish Audio / mock
- `calendar`: 飞书 / mock
- `weather`: OpenWeather / mock
- `music`: 网易云 / mock

关键原则：

- provider 负责能力接入
- tool 负责事实与候选内容
- agent 负责理解与编排

## 3. 主流程

### 生成电台

1. 移动端调用 `POST /api/station/generate`
2. 服务端读取 `device_context + user_state`
3. 调用天气 provider
4. 调用日程 provider
5. 读取用户记忆和历史
6. 拉取音乐 / 播客候选
7. 生成 `ContextSnapshot`
8. 调用 `RadioAgentRuntime`
9. Agent 输出 `RadioProgram`
10. TTS provider 为 greeting 生成语音地址
11. 保存 `StationSession`
12. 返回 `session + runtime status`

### 聊天

1. 移动端调用 `POST /api/chat`
2. 服务端读取当前 session
3. 记录 user message
4. 返回一条 agent reply
5. 后续可以把 chat history 纳入下一次 regenerate prompt

### 播放器状态

1. 移动端调用 `GET /api/player/{user_id}/now`
2. 服务端从 session store 取最近电台
3. 返回当前 item、queue、runtime status

## 4. 数据契约

核心 schema：

- `GenerateProgramRequest`
- `ContextSnapshot`
- `CalendarEvent`
- `RadioProgram`
- `StationSession`
- `StationGenerateResponse`
- `StationChatRequest`
- `StationChatResponse`
- `PlayerNowResponse`
- `RuntimeStatus`

## 5. 真实接线点

### DeepSeek

配置：

- `RADIO_AGENT_PROVIDER=deepseek`
- `DEEPSEEK_API_KEY`
- `DEEPSEEK_BASE_URL`
- `DEEPSEEK_MODEL`

落点：

- `server/app/agents/runtime.py`
- `server/app/services/providers.py`

### Fish Audio

配置：

- `TTS_PROVIDER=fish_audio`
- `FISH_AUDIO_API_KEY`
- `FISH_AUDIO_BASE_URL`
- `FISH_AUDIO_VOICE_ID`

落点：

- `server/app/services/providers.py`

当前状态：

- 已有 mock provider
- 真实 HTTP 接线待实现

### 飞书日程

配置：

- `CALENDAR_PROVIDER=feishu`
- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_CALENDAR_ID`

落点：

- `server/app/services/providers.py`

当前状态：

- 已经纳入 `calendar_events`
- 当前返回 mock events

### OpenWeather

配置：

- `WEATHER_PROVIDER=openweather`
- `OPENWEATHER_API_KEY`
- `OPENWEATHER_BASE_URL`

落点：

- `server/app/services/providers.py`

当前状态：

- 当前仍走 `server/app/tools/weather_tool.py` mock

### 网易云

配置：

- `NETEASE_API_BASE_URL`
- `NETEASE_COOKIE`
- `NETEASE_PLAYBACK_LEVEL`

落点：

- `server/app/tools/netease_music_tool.py`

当前状态：

- 已支持真实搜索和播放 URL 拉取
- 若不可用会回退 mock candidates

## 6. 为什么这样拆

这样拆的好处是：

- 前端可以稳定围绕 session 工作，不直接感知底层 provider 细节
- 真实 API 权限没到时，mock 流程也能完整跑通
- 拿到 API 权限后，我们只需要替换 provider，不需要再改主流程
- Agent 仍然处在决策中心，没有退化成文案润色器
