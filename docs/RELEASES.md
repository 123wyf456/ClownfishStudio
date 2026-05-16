# GitHub Releases

本仓库配置了桌面端自动打包工作流：

```text
.github/workflows/desktop-release.yml
```

工作流会在 GitHub Actions 上分别构建 Windows、macOS Intel、macOS Apple Silicon 三类桌面包，并上传 CI artifact。只有推送 `v*` tag 时，才会自动创建或更新 GitHub Release。

## 手动验证打包

在 GitHub 页面进入：

```text
Actions -> Desktop Release -> Run workflow
```

这只会产出 workflow artifacts，不会创建正式 Release。适合在发版前验证 Windows/macOS 是否都能打包成功。

## 正式发版

确认代码和版本号后，执行：

```bash
git tag v0.1.0
git push origin v0.1.0
```

CI 完成后，GitHub 会生成 Release，并上传类似这些文件：

```text
ClownfishStudio-0.1.0-windows-portable.exe
ClownfishStudio-0.1.0-mac-x64.dmg
ClownfishStudio-0.1.0-mac-x64.zip
ClownfishStudio-0.1.0-mac-arm64.dmg
ClownfishStudio-0.1.0-mac-arm64.zip
```

## CI 做了什么

每个平台都会先安装后端和桌面端依赖：

```bash
cd server
python -m venv --copies .venv
uv sync --locked --extra dev --link-mode copy --python .venv/bin/python
uv run --locked --python .venv/bin/python pytest -q
uv run --locked --python .venv/bin/python ruff check .
uv sync --locked --link-mode copy --python .venv/bin/python

cd ../desktop
npm ci
npm run build
```

然后按平台打包：

```bash
# Windows
npx electron-builder --win portable --publish never

# macOS Intel
npx electron-builder --mac dmg zip --x64 --publish never

# macOS Apple Silicon
npx electron-builder --mac dmg zip --arm64 --publish never
```

macOS 被拆成 Intel 和 Apple Silicon 两个 job，是因为桌面包会携带 `server/.venv`。Python 虚拟环境必须和目标平台架构一致，不能用一个 macOS runner 同时产出两种架构的后端运行时。

CI 会先用 `python -m venv --copies` 创建后端虚拟环境，再让 `uv` 以 `--link-mode copy` 安装依赖。这样 macOS `.app` 中不会出现指向 GitHub runner 或 uv 缓存目录的 Python 符号链接。

## 重要边界

- Release 包不会包含 `server/.env`，真实 API key、Cookie、TTS、天气等配置仍需要用户在应用内或运行时配置。
- CI 会在目标平台生成 `server/.venv`，所以打包产物内会带上对应平台的 Python 运行环境。
- macOS 产物当前是未签名包。第一次打开可能需要用户在系统安全设置里允许，后续正式分发需要 Apple Developer ID 签名和 notarization。
- Windows 产物当前也是未签名 portable exe。正式分发时建议配置代码签名证书，减少安全提示。
- 只有推送 `v*` tag 才会创建 GitHub Release；手动运行 workflow 只产出 artifacts。
