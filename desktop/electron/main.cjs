const { app, BrowserWindow, ipcMain, session, shell } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const { spawn } = require("node:child_process");
const { createDesktopApi } = require("./api-clients.cjs");

const isDev = Boolean(process.env.VITE_DEV_SERVER_URL);
let mainWindow;
let logFile;
let desktopApi;
let serverProcess = null;
let serverReadyPromise = null;

const SERVER_PORT = 8000;
const SERVER_HOST = "127.0.0.1";

function writeLog(message, detail) {
  try {
    if (!logFile) {
      const baseDir = resolveDesktopRuntimeRoot();
      fs.mkdirSync(baseDir, { recursive: true });
      logFile = path.join(baseDir, "clownfish-desktop.log");
    }

    const suffix = detail ? ` ${JSON.stringify(detail)}` : "";
    fs.appendFileSync(logFile, `${new Date().toISOString()} ${message}${suffix}\n`);
  } catch {
    // Logging must never affect app startup.
  }
}

async function ensureServerReady() {
  if (isDev) {
    return;
  }

  if (await isServerHealthy()) {
    writeLog("server:healthy-existing");
    return;
  }

  if (!serverReadyPromise) {
    serverReadyPromise = startBundledServer();
  }

  return serverReadyPromise;
}

function isServerHealthy() {
  return new Promise((resolve) => {
    const request = http.get(
      {
        host: SERVER_HOST,
        port: SERVER_PORT,
        path: "/health",
        timeout: 1500,
      },
      (response) => {
        response.resume();
        resolve(response.statusCode === 200);
      },
    );

    request.on("timeout", () => {
      request.destroy();
      resolve(false);
    });

    request.on("error", () => {
      resolve(false);
    });
  });
}

async function startBundledServer() {
  const serverPaths = resolveBundledServerPaths();
  if (!serverPaths) {
    writeLog("server:paths-missing");
    return;
  }

  const runtimeRoot = path.join(resolveDesktopRuntimeRoot(), "server-runtime");
  fs.mkdirSync(runtimeRoot, { recursive: true });

  writeLog("server:start", {
    pythonPath: serverPaths.pythonPath,
    serverWorkdir: serverPaths.serverWorkdir,
    runtimeRoot,
  });

  serverProcess = spawn(
    serverPaths.pythonPath,
    ["-m", "uvicorn", "app.main:app", "--host", SERVER_HOST, "--port", String(SERVER_PORT)],
    {
      cwd: serverPaths.serverWorkdir,
      env: {
        ...process.env,
        APP_ENV: "production",
        CLOWNFISH_RUNTIME_ROOT: runtimeRoot,
      },
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    },
  );

  serverProcess.stdout.on("data", (chunk) => {
    writeLog("server:stdout", { text: String(chunk).trim() });
  });

  serverProcess.stderr.on("data", (chunk) => {
    writeLog("server:stderr", { text: String(chunk).trim() });
  });

  serverProcess.on("exit", (code, signal) => {
    writeLog("server:exit", { code, signal });
    serverProcess = null;
    serverReadyPromise = null;
  });

  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (await isServerHealthy()) {
      writeLog("server:ready");
      return;
    }

    if (!serverProcess) {
      break;
    }

    await delay(500);
  }

  throw new Error("Bundled server failed to become healthy within 30s");
}

function resolveBundledServerPaths() {
  const baseResources = app.isPackaged
    ? path.join(process.resourcesPath, "backend", "server")
    : path.join(__dirname, "..", "..", "server");

  const pythonCandidates = buildPythonCandidates(baseResources);
  const pythonPath = pythonCandidates.find((candidate) => fs.existsSync(candidate));
  const serverWorkdir = app.isPackaged ? baseResources : path.join(__dirname, "..", "..", "server");

  if (!pythonPath || !fs.existsSync(serverWorkdir)) {
    writeLog("server:paths-missing", {
      serverWorkdir,
      pythonCandidates,
    });
    return null;
  }

  return {
    pythonPath,
    serverWorkdir,
  };
}

function buildPythonCandidates(serverRoot) {
  const windowsCandidates = [
    path.join(serverRoot, ".venv", "Scripts", "python.exe"),
    path.join(serverRoot, ".venv", "Scripts", "python"),
  ];
  const posixCandidates = [
    path.join(serverRoot, ".venv", "bin", "python3"),
    path.join(serverRoot, ".venv", "bin", "python"),
  ];
  return process.platform === "win32"
    ? [...windowsCandidates, ...posixCandidates]
    : [...posixCandidates, ...windowsCandidates];
}

function resolveDesktopRuntimeRoot() {
  const configuredRoot = process.env.CLOWNFISH_DESKTOP_RUNTIME_ROOT;
  if (configuredRoot && configuredRoot.trim()) {
    return path.resolve(configuredRoot.trim());
  }

  if (app.isPackaged && process.platform === "darwin") {
    return app.getPath("userData");
  }

  const appRoot = app.isPackaged
    ? process.env.PORTABLE_EXECUTABLE_DIR || path.dirname(process.execPath)
    : path.resolve(__dirname, "..", "..");
  return path.join(appRoot, "runtime");
}

function migrateRuntimeConfig(runtimeRoot) {
  const oldRoot = app.getPath("userData");
  if (!oldRoot || path.resolve(oldRoot) === path.resolve(runtimeRoot)) {
    return;
  }

  copyFileIfMissing(
    path.join(oldRoot, "desktop-settings.json"),
    path.join(runtimeRoot, "desktop-settings.json"),
  );
  copyFileIfMissing(
    path.join(oldRoot, "server-runtime", ".env"),
    path.join(runtimeRoot, "server-runtime", ".env"),
  );
}

function copyFileIfMissing(sourcePath, targetPath) {
  try {
    if (!fs.existsSync(sourcePath) || fs.existsSync(targetPath)) {
      return;
    }
    fs.mkdirSync(path.dirname(targetPath), { recursive: true });
    fs.copyFileSync(sourcePath, targetPath);
    writeLog("runtime:migrated-file", { sourcePath, targetPath });
  } catch (error) {
    writeLog("runtime:migration-failed", {
      sourcePath,
      targetPath,
      message: error instanceof Error ? error.message : String(error),
    });
  }
}

function delay(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

process.on("uncaughtException", (error) => {
  writeLog("uncaughtException", { message: error.message, stack: error.stack });
});

process.on("unhandledRejection", (reason) => {
  writeLog("unhandledRejection", { reason: String(reason) });
});

function createWindow() {
  writeLog("createWindow:start", { isDev, packaged: app.isPackaged });

  mainWindow = new BrowserWindow({
    width: 540,
    height: 960,
    minWidth: 540,
    minHeight: 960,
    maxWidth: 540,
    maxHeight: 960,
    title: "ClownfishStudio",
    transparent: false,
    backgroundColor: "#050505",
    resizable: false,
    show: true,
    ...(process.platform === "darwin"
      ? {
          titleBarStyle: "hiddenInset",
          trafficLightPosition: { x: 18, y: 18 },
        }
      : {
          frame: false,
        }),
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  mainWindow.once("ready-to-show", () => {
    writeLog("window:ready-to-show", {
      bounds: mainWindow.getBounds(),
      contentBounds: mainWindow.getContentBounds(),
    });
  });

  mainWindow.on("close", () => {
    writeLog("window:close");
  });

  mainWindow.on("closed", () => {
    writeLog("window:closed");
    mainWindow = undefined;
  });

  mainWindow.webContents.on("did-finish-load", () => {
    writeLog("webContents:did-finish-load");
    mainWindow.webContents
      .executeJavaScript(
        "({ title: document.title, rootChildren: document.getElementById('root')?.children.length ?? -1, textLength: document.body.innerText.length, bodyClientHeight: document.body.clientHeight, bodyScrollHeight: document.body.scrollHeight, mainClientHeight: document.querySelector('main')?.clientHeight ?? -1, mainScrollHeight: document.querySelector('main')?.scrollHeight ?? -1 })",
      )
      .then((state) => {
        writeLog("webContents:dom-state", state);
      })
      .catch((error) => {
        writeLog("webContents:dom-state-failed", { message: error.message });
      });
  });

  mainWindow.webContents.on("console-message", (_event, level, message) => {
    writeLog("webContents:console-message", { level, message });
  });

  mainWindow.webContents.on("did-fail-load", (_event, errorCode, errorDescription, validatedURL) => {
    writeLog("webContents:did-fail-load", { errorCode, errorDescription, validatedURL });
  });

  mainWindow.webContents.on("render-process-gone", (_event, details) => {
    writeLog("webContents:render-process-gone", details);
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  if (isDev) {
    writeLog("loadURL", { url: process.env.VITE_DEV_SERVER_URL });
    mainWindow.loadURL(process.env.VITE_DEV_SERVER_URL);
  } else {
    const indexPath = path.join(__dirname, "..", "dist", "index.html");
    writeLog("loadFile", { indexPath, exists: fs.existsSync(indexPath) });
    mainWindow.loadFile(indexPath);
  }
}

app.whenReady().then(() => {
  writeLog("app:ready");
  const runtimeRoot = resolveDesktopRuntimeRoot();
  migrateRuntimeConfig(runtimeRoot);

  ipcMain.handle("window:minimize", (event) => {
    BrowserWindow.fromWebContents(event.sender)?.minimize();
  });

  ipcMain.handle("window:close", (event) => {
    BrowserWindow.fromWebContents(event.sender)?.close();
  });

  desktopApi = createDesktopApi({
    app,
    runtimeRoot,
    writeLog,
  });
  configurePermissions();

  ipcMain.handle("api:get-config", () =>
    timedIpc("api:get-config", () => callWhenServerReady(() => desktopApi.getConfig())),
  );
  ipcMain.handle("api:save-config", (_event, payload) =>
    timedIpc("api:save-config", () => callWhenServerReady(() => desktopApi.saveConfig(payload))),
  );
  ipcMain.handle("api:generate-station", (_event, payload) =>
    timedIpc("api:generate-station", () =>
      callWhenServerReady(() => desktopApi.generateStation(payload)),
    ),
  );
  ipcMain.handle("api:chat-station", (_event, payload) =>
    timedIpc("api:chat-station", () =>
      callWhenServerReady(() => desktopApi.chatStation(payload)),
    ),
  );
  ipcMain.handle("api:advance-player", (_event, payload) =>
    timedIpc("api:advance-player", () =>
      callWhenServerReady(() => desktopApi.advancePlayer(payload)),
    ),
  );

  createWindow();
  startServerInBackground();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

function startServerInBackground() {
  ensureServerReady().catch((error) => {
    writeLog("server:start-failed", {
      message: error instanceof Error ? error.message : String(error),
    });
  });
}

async function callWhenServerReady(callback) {
  await ensureServerReady();
  return callback();
}

function configurePermissions() {
  const ses = session.defaultSession;
  ses.setPermissionCheckHandler((_webContents, permission) => {
    return permission === "geolocation";
  });
  ses.setPermissionRequestHandler((_webContents, permission, callback) => {
    callback(permission === "geolocation");
  });
}

async function timedIpc(label, callback) {
  const startedAt = Date.now();
  writeLog(`${label}:start`);
  try {
    const result = await callback();
    writeLog(`${label}:end`, { durationMs: Date.now() - startedAt });
    return result;
  } catch (error) {
    writeLog(`${label}:failed`, {
      durationMs: Date.now() - startedAt,
      message: error instanceof Error ? error.message : String(error),
    });
    throw error;
  }
}

app.on("window-all-closed", () => {
  writeLog("app:window-all-closed");
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  writeLog("app:before-quit");
  if (serverProcess) {
    try {
      serverProcess.kill();
    } catch {
      // Best effort on shutdown.
    }
  }
});
