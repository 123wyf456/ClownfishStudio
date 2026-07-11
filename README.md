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

### Windows 本地打包

项目根目录提供了 Windows portable exe 打包脚本：

```powershell
.\scripts\package_windows.ps1
```

脚本会依次执行：

1. `server` 后端依赖同步：`uv sync`
2. 后端测试：`uv run python -m pytest -q`
3. 后端 lint：`uv run python -m ruff check .`
4. `desktop` 前端依赖安装：`npm install`
5. 清理旧的 `desktop\release` 输出
6. Windows portable exe 打包：`npm run dist:win`
7. 移除 `win-unpacked`、builder 调试文件和运行时目录等中间内容

打包产物输出在：

```text
desktop\release\ClownfishStudio.exe
```

正常打包完成后，`desktop\release` 里只需要保留这个 portable exe。`win-unpacked` 是 electron-builder 生成 portable exe 时的中间展开目录，不需要手动分发。

如果本机依赖已经准备好，可以跳过依赖安装：

```powershell
.\scripts\package_windows.ps1 -SkipInstall
```

如果只是快速验证打包流程，可以跳过测试和 lint：

```powershell
.\scripts\package_windows.ps1 -SkipChecks
```
