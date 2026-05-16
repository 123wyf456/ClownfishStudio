# ClownfishStudio

ClownfishStudio 是一个 AI 电台应用。

它会根据你当前的状态、时间、天气和偏好，帮你生成一档“此刻适合听”的个人电台。你可以直接播放，也可以像和电台聊天一样告诉它你此刻的想法。

ClownfishStudio 的目标不是做一个普通播放器，而是让你感觉像有人正在为你实时编排一档电台节目。

## API 配置

右上角进入配置界面

- AGENT：填写模型服务的 API Key。
- 天气：填写 OpenWeather API Key。
- 语音：填写 Fish Audio API Key。
- 网易云音乐：填写网易云相关服务地址和 Cookie。

ps：天气和语音的接口暂时关掉了

### 启动网易云服务

https://github.com/nooblong/NeteaseCloudMusicApiBackup.git

拉代码下来

```
npm install
node app.js
```

打开网页登陆网易云账号，F12 -> Network -> 筛选weapi -> 获取cookie

## 使用方法

### release：

1. 双击打开 ClownfishStudio。
2. 进入设置页，按需填写 API 信息。
3. 回到首页，生成今日电台。
4. 点击播放。
5. 想调整风格时，直接在聊天里告诉它你的需求。

### 源码运行：

```powershell
cd server
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```powershell
cd desktop
npm install
npm run dev
```