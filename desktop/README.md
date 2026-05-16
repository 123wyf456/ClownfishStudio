# ClownfishStudio Desktop

Windows / macOS desktop client for ClownfishStudio.

## Stack

- Electron
- React
- TypeScript
- Tailwind CSS
- Framer Motion
- shadcn/ui-style primitives

## Commands

```bash
npm install
npm run dev
npm run build
npm run dist
npm run dist:win
npm run dist:mac
```

`npm run dist` builds for the current host platform. To build a specific target:

```bash
npm run dist:win
npm run dist:mac
```

Windows output:

```text
release/ClownfishStudio-0.1.0-windows-portable.exe
```

macOS output:

```text
release/ClownfishStudio-0.1.0-mac-arm64.dmg
release/ClownfishStudio-0.1.0-mac-x64.dmg
```

macOS packages must be built on macOS. The bundled backend also expects a
platform-native Python virtual environment:

```text
server/.venv/Scripts/python.exe   # Windows
server/.venv/bin/python3          # macOS
server/.venv/bin/python           # macOS fallback
```

If GitHub download access is slow when packaging NSIS resources, run:

```powershell
$env:ELECTRON_BUILDER_BINARIES_MIRROR='https://npmmirror.com/mirrors/electron-builder-binaries/'
npm run dist:win
```

If the executable immediately exits when launched from a terminal, make sure the
terminal is not forcing Electron to run as Node:

```powershell
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
.\release\ClownfishStudio-0.1.0-windows-portable.exe
```

## Current Scope

The current client is a fixed-size 540 x 960 desktop app with:

- light and dark themes
- a turntable-inspired player surface
- companion chat inside the same device frame
- settings for Agent, OpenWeather, NetEase Cloud Music, and Fish Audio
- native macOS traffic lights in macOS builds
- persistent NetEase metadata cache under app user data to speed up relaunches
- local music caching for remote NetEase playback URLs

Provider failures do not stop the app. Missing keys, expired NetEase cookies,
empty search results, or failed TTS requests are surfaced as warnings and the
client falls back to mock content when possible.

## Runtime Architecture

The desktop app is a thin Electron shell over the FastAPI backend in `server/`.

```text
renderer UI -> Electron IPC -> local FastAPI server -> tools/providers/agent -> renderer playback
```

Packaged builds bundle the backend and start it automatically on
`http://127.0.0.1:8000`.

Runtime-generated data is stored under the app user data directory:

```text
desktop-settings.json
server-runtime/.env
server-runtime/clownfishstudio.db
server-runtime/generated_audio/
cached-music/
```

That keeps API keys, generated audio, and the SQLite database outside the app
install directory and outside Git.
