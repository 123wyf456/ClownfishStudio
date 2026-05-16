# ClownfishStudio

## 1. 简单自我介绍

ClownfishStudio 是一个 AI 电台应用。

它会根据你当前的状态、时间、天气和偏好，帮你生成一档“此刻适合听”的个人电台。你可以直接播放，也可以像和电台聊天一样告诉它你此刻的想法。

ClownfishStudio 的目标不是做一个普通播放器，而是让你感觉像有人正在为你实时编排一档电台节目。

## 2. 配置 API 方法

不配置 API 也可以先体验，默认会使用 mock 模式。

如果想使用真实 AI、天气、语音或音乐服务，可以在应用里的设置页面填写 API 信息。

常用配置：

- AI：填写模型服务的 API Key。
- 天气：填写 OpenWeather API Key。
- 语音：填写 Fish Audio API Key。
- 网易云音乐：填写网易云相关服务地址和 Cookie。

ps：天气和语音的接口暂时关掉了

## 3. 使用方法

### release：

1. 双击打开 ClownfishStudio。
2. 进入设置页，按需填写 API 信息。
3. 回到首页，生成今日电台。
4. 点击播放。
5. 想调整风格时，直接在聊天里告诉它你的需求。

### 源码运行：

先启动后端：

```powershell
cd server
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

再启动桌面端：

```powershell
cd desktop
npm install
npm run dev
```