const fs = require("node:fs");
const path = require("node:path");

const DEFAULT_TASTE_MD = `# Taste Notes

- Prefer tracks from the user's real NetEase listening history and playlists.
- Favor short hosted sets over plain search results when possible.
- Use recent listening history as a freshness signal, not a hard rule.
`;

const DEFAULT_ROUTINES_MD = `# Routines

- Keep the opening greeting short and grounded in weather, time, and the user's request.
- Use calm late-night phrasing when the hour is late.
- Keep chat replies focused on the next playable set, not on explanation.
`;

const DEFAULT_PLAYLISTS = {
  updatedAt: null,
  playlists: [],
};

const DEFAULT_SCHEDULE = {
  updatedAt: null,
  timezone: "Asia/Shanghai",
  events: [],
};

const DEFAULT_ENVIRONMENT = {
  updatedAt: null,
  city: "Shanghai",
  weather: "",
  condition: "",
  temperature: null,
  localTime: null,
  timezone: "Asia/Shanghai",
};

const DEFAULT_HISTORY = {
  updatedAt: null,
  sessions: [],
  chats: [],
};

function createContextStore(userDataDir, writeLog) {
  const rootDir = path.join(userDataDir, "clownfish-context");
  const files = {
    tasteMd: path.join(rootDir, "taste.md"),
    routinesMd: path.join(rootDir, "routines.md"),
    playlistsJson: path.join(rootDir, "playlists.json"),
    scheduleJson: path.join(rootDir, "schedule.json"),
    environmentJson: path.join(rootDir, "environment.json"),
    historyJson: path.join(rootDir, "history.json"),
  };

  fs.mkdirSync(rootDir, { recursive: true });
  ensureTextFile(files.tasteMd, DEFAULT_TASTE_MD);
  ensureTextFile(files.routinesMd, DEFAULT_ROUTINES_MD);
  ensureJsonFile(files.playlistsJson, DEFAULT_PLAYLISTS);
  ensureJsonFile(files.scheduleJson, DEFAULT_SCHEDULE);
  ensureJsonFile(files.environmentJson, DEFAULT_ENVIRONMENT);
  ensureJsonFile(files.historyJson, DEFAULT_HISTORY);

  function loadContextFiles() {
    return {
      tasteMd: readText(files.tasteMd, DEFAULT_TASTE_MD),
      routinesMd: readText(files.routinesMd, DEFAULT_ROUTINES_MD),
      playlists: readJson(files.playlistsJson, DEFAULT_PLAYLISTS),
      schedule: readJson(files.scheduleJson, DEFAULT_SCHEDULE),
      environment: readJson(files.environmentJson, DEFAULT_ENVIRONMENT),
      history: readJson(files.historyJson, DEFAULT_HISTORY),
    };
  }

  function saveSessionSnapshot(snapshot) {
    const nextEnvironment = {
      ...readJson(files.environmentJson, DEFAULT_ENVIRONMENT),
      ...snapshot.environment,
      updatedAt: new Date().toISOString(),
    };
    writeJson(files.environmentJson, nextEnvironment);

    if (snapshot.playlists) {
      const nextPlaylists = {
        ...readJson(files.playlistsJson, DEFAULT_PLAYLISTS),
        ...snapshot.playlists,
        updatedAt: new Date().toISOString(),
      };
      writeJson(files.playlistsJson, nextPlaylists);
    }

    const history = readJson(files.historyJson, DEFAULT_HISTORY);
    const nextHistory = {
      ...history,
      updatedAt: new Date().toISOString(),
      sessions: [
        ...(Array.isArray(history.sessions) ? history.sessions : []),
        ...(Array.isArray(snapshot.sessions) ? snapshot.sessions : []),
      ].slice(-50),
      chats: [
        ...(Array.isArray(history.chats) ? history.chats : []),
        ...(Array.isArray(snapshot.chats) ? snapshot.chats : []),
      ].slice(-100),
    };
    writeJson(files.historyJson, nextHistory);
  }

  function appendChat(chatEntry) {
    const history = readJson(files.historyJson, DEFAULT_HISTORY);
    const nextHistory = {
      ...history,
      updatedAt: new Date().toISOString(),
      chats: [
        ...(Array.isArray(history.chats) ? history.chats : []),
        chatEntry,
      ].slice(-100),
    };
    writeJson(files.historyJson, nextHistory);
  }

  function buildPromptSection() {
    const context = loadContextFiles();
    return {
      taste_md: context.tasteMd,
      routines_md: context.routinesMd,
      playlists_json: context.playlists,
      schedule_json: context.schedule,
      environment_json: context.environment,
      history_json: context.history,
    };
  }

  return {
    rootDir,
    files,
    loadContextFiles,
    saveSessionSnapshot,
    appendChat,
    buildPromptSection,
  };
}

function ensureTextFile(filePath, fallback) {
  if (fs.existsSync(filePath)) {
    return;
  }
  fs.writeFileSync(filePath, fallback, "utf-8");
}

function ensureJsonFile(filePath, fallback) {
  if (fs.existsSync(filePath)) {
    return;
  }
  fs.writeFileSync(filePath, JSON.stringify(fallback, null, 2), "utf-8");
}

function readText(filePath, fallback) {
  try {
    return fs.readFileSync(filePath, "utf-8");
  } catch {
    return fallback;
  }
}

function readJson(filePath, fallback) {
  try {
    const raw = fs.readFileSync(filePath, "utf-8");
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : fallback;
  } catch {
    return fallback;
  }
}

function writeJson(filePath, value) {
  fs.writeFileSync(filePath, JSON.stringify(value, null, 2), "utf-8");
}

module.exports = {
  createContextStore,
};
