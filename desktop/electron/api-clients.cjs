const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

let electronNet = null;
try {
  const electron = require("electron");
  if (electron && typeof electron === "object" && electron.net) {
    electronNet = electron.net;
  }
} catch {
  electronNet = null;
}

const DEFAULT_CONFIG = {
  serverBaseUrl: "http://127.0.0.1:8000",
};

function createDesktopApi({ app, runtimeRoot, writeLog }) {
  const desktopRuntimeRoot = runtimeRoot || app.getPath("userData");
  const configPath = path.join(desktopRuntimeRoot, "desktop-settings.json");
  const musicDir = path.join(desktopRuntimeRoot, "cached-music");

  fs.mkdirSync(path.dirname(configPath), { recursive: true });
  fs.mkdirSync(musicDir, { recursive: true });
  writeLog("desktopApi:runtimeRoot", {
    runtimeRoot: desktopRuntimeRoot,
    configPath,
    musicDir,
  });

  function readConfig() {
    try {
      if (!fs.existsSync(configPath)) {
        return { ...DEFAULT_CONFIG };
      }
      const parsed = JSON.parse(fs.readFileSync(configPath, "utf-8"));
      return sanitizeLocalConfig({ ...DEFAULT_CONFIG, ...parsed });
    } catch (error) {
      writeLog("desktopApi:readConfigFailed", { message: error.message });
      return { ...DEFAULT_CONFIG };
    }
  }

  function writeConfig(nextConfig) {
    const config = sanitizeLocalConfig({ ...DEFAULT_CONFIG, ...readConfig(), ...nextConfig });
    fs.writeFileSync(configPath, JSON.stringify(config, null, 2), "utf-8");
    return config;
  }

  async function getConfig() {
    const startedAt = Date.now();
    const localConfig = readConfig();
    writeLog("desktopApi:getConfig:start", { serverBaseUrl: localConfig.serverBaseUrl });
    try {
      const remote = await requestJson(localConfig.serverBaseUrl, "/api/config", {
        method: "GET",
      });
      writeLog("desktopApi:getConfig:end", { durationMs: Date.now() - startedAt });
      return {
        ...remote,
        local: localConfig,
      };
    } catch (error) {
      writeLog("desktopApi:getConfig:failed", {
        durationMs: Date.now() - startedAt,
        message: error instanceof Error ? error.message : String(error),
      });
      throw error;
    }
  }

  async function saveConfig(payload) {
    const startedAt = Date.now();
    const localConfig = writeConfig({
      serverBaseUrl: payload?.serverBaseUrl || readConfig().serverBaseUrl,
    });
    writeLog("desktopApi:saveConfig:start", {
      serverBaseUrl: localConfig.serverBaseUrl,
      agentProvider: payload?.agentProvider,
      hasAgentKey: Boolean(payload?.agentApiKey),
      hasTtsKey: Boolean(payload?.fishAudioApiKey),
      hasNeteaseCookie: Boolean(payload?.neteaseCookie),
    });
    const remotePayload = {
      radio_agent_provider: payload.agentProvider,
      radio_agent_model: payload.agentModel,
      openai_api_key: payload.agentProvider === "openai" ? payload.agentApiKey : "",
      openai_base_url: payload.agentProvider === "openai" ? payload.agentBaseUrl : "https://api.openai.com/v1",
      anthropic_api_key: payload.agentProvider === "anthropic" ? payload.agentApiKey : "",
      anthropic_base_url: payload.agentProvider === "anthropic" ? payload.agentBaseUrl : "https://api.anthropic.com",
      tts_provider: "fish_audio",
      fish_audio_api_key: payload.fishAudioApiKey,
      fish_audio_base_url: payload.fishAudioBaseUrl,
      fish_audio_voice_id: payload.fishAudioVoiceId,
      calendar_provider: "mock",
      feishu_app_id: "",
      feishu_app_secret: "",
      feishu_calendar_id: "",
      weather_provider: "disabled",
      openweather_api_key: "",
      openweather_base_url: payload.openweatherBaseUrl,
      netease_api_base_url: payload.neteaseApiBaseUrl,
      netease_cookie: payload.neteaseCookie,
      netease_playback_level: payload.neteasePlaybackLevel,
    };
    try {
      const remote = await requestJson(localConfig.serverBaseUrl, "/api/config", {
        method: "PUT",
        body: remotePayload,
      });
      writeLog("desktopApi:saveConfig:end", { durationMs: Date.now() - startedAt });
      return {
        ...remote,
        local: localConfig,
      };
    } catch (error) {
      writeLog("desktopApi:saveConfig:failed", {
        durationMs: Date.now() - startedAt,
        message: error instanceof Error ? error.message : String(error),
      });
      throw error;
    }
  }

  async function generateStation(payload = {}) {
    const startedAt = Date.now();
    const localConfig = readConfig();
    const deviceContext = await buildDeviceContext(payload.deviceLocation);
    const requestPayload = {
      user_id: "desktop-user",
      device_context: deviceContext,
      user_state: {
        duration_minutes: 25,
        needs: ["companionship"],
        free_text:
          payload.message || "Open ClownfishStudio and create a fresh hosted radio set.",
      },
      max_candidates: 16,
    };
    writeLog("desktopApi:generateStation:start", {
      cityHint: deviceContext.city_hint || "",
      hasCoordinates: Number.isFinite(deviceContext.latitude) && Number.isFinite(deviceContext.longitude),
      messageLength: String(payload.message || "").length,
    });
    try {
      const requestStartedAt = Date.now();
      const response = await requestJson(localConfig.serverBaseUrl, "/api/station/generate", {
        method: "POST",
        body: requestPayload,
      });
      const requestDurationMs = Date.now() - requestStartedAt;
      const normalizeStartedAt = Date.now();
      const normalized = await normalizeStationResponse(response, localConfig, musicDir);
      writeLog("desktopApi:generateStation:end", {
        durationMs: Date.now() - startedAt,
        requestDurationMs,
        normalizeDurationMs: Date.now() - normalizeStartedAt,
      });
      return normalized;
    } catch (error) {
      writeLog("desktopApi:generateStation:failed", {
        durationMs: Date.now() - startedAt,
        message: error instanceof Error ? error.message : String(error),
      });
      throw error;
    }
  }

  async function chatStation(payload = {}) {
    const startedAt = Date.now();
    const localConfig = readConfig();
    const message = String(payload.message || "").trim();
    if (!message) {
      return generateStation(payload);
    }
    const deviceContext = await buildDeviceContext(payload.deviceLocation);
    writeLog("desktopApi:chatStation:start", {
      cityHint: deviceContext.city_hint || "",
      hasCoordinates: Number.isFinite(deviceContext.latitude) && Number.isFinite(deviceContext.longitude),
      messageLength: message.length,
    });
    try {
      const requestStartedAt = Date.now();
      const response = await requestJson(localConfig.serverBaseUrl, "/api/chat", {
        method: "POST",
        body: {
          user_id: "desktop-user",
          message,
          device_context: deviceContext,
        },
      });
      const requestDurationMs = Date.now() - requestStartedAt;
      const normalizeStartedAt = Date.now();
      const normalized = await normalizeStationResponse(response, localConfig, musicDir);
      writeLog("desktopApi:chatStation:end", {
        durationMs: Date.now() - startedAt,
        requestDurationMs,
        normalizeDurationMs: Date.now() - normalizeStartedAt,
      });
      return normalized;
    } catch (error) {
      writeLog("desktopApi:chatStation:failed", {
        durationMs: Date.now() - startedAt,
        message: error instanceof Error ? error.message : String(error),
      });
      throw error;
    }
  }

  return {
    getConfig,
    saveConfig,
    generateStation,
    chatStation,
  };
}

function sanitizeLocalConfig(config) {
  return {
    serverBaseUrl:
      typeof config.serverBaseUrl === "string" && config.serverBaseUrl.trim()
        ? config.serverBaseUrl.trim().replace(/\/$/, "")
        : DEFAULT_CONFIG.serverBaseUrl,
  };
}

async function buildDeviceContext(deviceLocation) {
  const now = new Date();
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const locale = Intl.DateTimeFormat().resolvedOptions().locale || "zh-CN";
  const location = normalizeDeviceLocation(deviceLocation);
  return {
    local_time: now.toISOString(),
    timezone,
    locale,
    city_hint: location.cityHint || "",
    latitude: location.latitude,
    longitude: location.longitude,
  };
}

function normalizeDeviceLocation(deviceLocation) {
  if (!deviceLocation || typeof deviceLocation !== "object") {
    return {};
  }

  const latitude =
    typeof deviceLocation.latitude === "number" && Number.isFinite(deviceLocation.latitude)
      ? deviceLocation.latitude
      : undefined;
  const longitude =
    typeof deviceLocation.longitude === "number" && Number.isFinite(deviceLocation.longitude)
      ? deviceLocation.longitude
      : undefined;
  const cityHint =
    typeof deviceLocation.cityHint === "string" && deviceLocation.cityHint.trim()
      ? deviceLocation.cityHint.trim()
      : "";

  return { latitude, longitude, cityHint };
}

async function normalizeStationResponse(payload, localConfig, musicDir) {
  const session = payload?.session || {};
  const program = session?.program || {};
  const blocks = Array.isArray(program?.blocks) ? program.blocks : [];
  const playableItems = blocks
    .flatMap((block) => (Array.isArray(block?.items) ? block.items : []))
    .filter((item) => item?.item_type !== "narration" && item?.candidate_id);

  const tracks = playableItems.slice(0, 18).map((item, index) => {
    const remotePlaybackUrl = item.playback_url || "";
    const cachedPlaybackUrl = getCachedPlaybackUrl(remotePlaybackUrl, musicDir);
    warmPlaybackCache(remotePlaybackUrl, musicDir);
    return {
      id: item.item_id || `track-${index}`,
      candidateId: item.candidate_id || `candidate-${index}`,
      title: item.title || "Untitled",
      artist: item.creator || "Unknown artist",
      duration: Number(item.duration_seconds || 180),
      playbackUrl: cachedPlaybackUrl || remotePlaybackUrl,
      source: "server",
    };
  });

  const weather = session?.weather || {};
  const assistantText =
    payload?.reply?.text || session?.greeting || program?.summary || "The station is ready.";

  return {
    station: {
      id: session?.session_id || `session-${crypto.randomUUID()}`,
      title: program?.title || "ClownfishStudio Radio",
      subtitle:
        blocks[0]?.title ||
        program?.summary ||
        "Agent Mix",
      city: weather?.city || "Unknown",
      condition: weather?.condition || "...",
      temperature: Number(weather?.temperature_celsius ?? 0),
      weather: weather?.condition || "...",
      agentLine: assistantText,
      ttsAudioUrl: resolveServerAssetUrl(localConfig.serverBaseUrl, session?.tts_audio_url || ""),
      tracks: tracks.length > 0 ? tracks : fallbackTracks(),
      chatReply: payload?.reply?.text || "",
      greeting: session?.greeting || "",
      sessionId: session?.session_id || "",
    },
    runtime: mapRuntime(payload?.runtime),
    warnings: Array.isArray(session?.warnings)
      ? session.warnings
      : Array.isArray(payload?.warnings)
        ? payload.warnings
        : [],
  };
}

function mapRuntime(runtime) {
  if (!runtime || typeof runtime !== "object") {
    return {
      agent: { provider: "mock", configured: true, mode: "mock" },
      weather: { provider: "disabled", configured: false, mode: "disabled" },
      music: { provider: "mock", configured: false, mode: "mock" },
      tts: { provider: "mock", configured: false, mode: "mock" },
    };
  }

  return {
    agent: runtime.brain || { provider: "mock", configured: true, mode: "mock" },
    weather: runtime.weather || { provider: "disabled", configured: false, mode: "disabled" },
    music: runtime.music || { provider: "mock", configured: false, mode: "mock" },
    tts: runtime.tts || { provider: "mock", configured: false, mode: "mock" },
  };
}

function resolveServerAssetUrl(serverBaseUrl, value) {
  if (!value || typeof value !== "string") {
    return "";
  }
  if (/^https?:\/\//i.test(value) || /^file:\/\//i.test(value)) {
    return value;
  }
  return `${String(serverBaseUrl || "").replace(/\/$/, "")}${value.startsWith("/") ? value : `/${value}`}`;
}

async function normalizePlaybackUrl(playbackUrl, musicDir, warnings) {
  if (!playbackUrl || !isHttpUrl(playbackUrl)) {
    return playbackUrl;
  }
  const cached = await cacheRemoteTrack(playbackUrl, musicDir, warnings);
  return cached || playbackUrl;
}

function warmPlaybackCache(playbackUrl, musicDir) {
  if (!playbackUrl || !isHttpUrl(playbackUrl)) {
    return;
  }
  cacheRemoteTrack(playbackUrl, musicDir, [])
    .then((cachedUrl) => {
      if (cachedUrl) {
        // Cached file will be reused by later sessions without blocking this response.
      }
    })
    .catch(() => {
      // Best effort only; playback should use the original remote URL.
    });
}

function getCachedPlaybackUrl(sourceUrl, musicDir) {
  if (!sourceUrl || !isHttpUrl(sourceUrl)) {
    return "";
  }
  const trackId = sanitizeFilePart(sourceUrl);
  const cacheKey = crypto.createHash("sha256").update(sourceUrl).digest("hex").slice(0, 18);
  const candidates = ["mp3", "m4a", "aac", "ogg", "wav", "flac"].map((ext) =>
    path.join(musicDir, `${trackId}-${cacheKey}.${ext}`),
  );
  const cachedPath = candidates.find((candidatePath) => isUsableFile(candidatePath));
  return cachedPath ? pathToFileURL(cachedPath).toString() : "";
}

async function requestJson(serverBaseUrl, endpoint, options) {
  const response = await fetch(`${serverBaseUrl}${endpoint}`, {
    method: options.method || "GET",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${endpoint} ${response.status} ${detail}`.trim());
  }
  return response.json();
}

async function cacheRemoteTrack(sourceUrl, musicDir, warnings) {
  const trackId = sanitizeFilePart(sourceUrl);
  const cacheKey = crypto.createHash("sha256").update(sourceUrl).digest("hex").slice(0, 18);
  const initialExt = inferAudioExtension(sourceUrl, "", Buffer.alloc(0));
  const initialPath = path.join(musicDir, `${trackId}-${cacheKey}.${initialExt}`);

  if (isUsableFile(initialPath)) {
    return pathToFileURL(initialPath).toString();
  }

  try {
    const response = await requestBinary(sourceUrl, {
      headers: {
        Accept: "audio/mpeg, audio/*, application/octet-stream, */*",
        Referer: "https://music.163.com/",
        "User-Agent": "ClownfishStudio/0.1.0",
      },
      preferElectronNet: true,
      timeoutMs: 45_000,
    });
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw new Error(describeHttpFailure("NetEase audio", response));
    }

    const contentType = getHeaderValue(response.headers, "content-type");
    if (!isPlayableAudioBuffer(response.buffer, contentType)) {
      throw new Error(describeHttpFailure("NetEase audio returned non-audio content", response));
    }

    const ext = inferAudioExtension(sourceUrl, contentType, response.buffer);
    const outputPath = path.join(musicDir, `${trackId}-${cacheKey}.${ext}`);
    const tempPath = `${outputPath}.tmp`;
    fs.mkdirSync(path.dirname(outputPath), { recursive: true });
    fs.writeFileSync(tempPath, response.buffer);
    fs.renameSync(tempPath, outputPath);
    return pathToFileURL(outputPath).toString();
  } catch (error) {
    warnings.push(
      `Audio cache failed: ${describeError(error)}. Falling back to stream URL.`,
    );
    return "";
  }
}

async function requestBinary(url, options = {}) {
  const errors = [];
  if (options.preferElectronNet && electronNet) {
    try {
      return await requestBinaryWithElectronNet(url, options);
    } catch (error) {
      errors.push(error);
    }
  }

  try {
    return await requestBinaryWithFetch(url, options);
  } catch (error) {
    errors.push(error);
  }

  if (!options.preferElectronNet && electronNet) {
    try {
      return await requestBinaryWithElectronNet(url, options);
    } catch (error) {
      errors.push(error);
    }
  }

  const message = errors.map((error) => describeError(error)).filter(Boolean).join("; ");
  throw new Error(message || "binary request failed");
}

async function requestBinaryWithFetch(url, options = {}) {
  const controller = new AbortController();
  const timeout = windowlessTimeout(() => controller.abort(), options.timeoutMs || 30_000);
  try {
    const response = await fetch(url, {
      method: options.method || "GET",
      headers: options.headers || {},
      body: options.body,
      signal: controller.signal,
    });
    const buffer = Buffer.from(await response.arrayBuffer());
    return {
      statusCode: response.status,
      headers: Object.fromEntries(response.headers.entries()),
      buffer,
    };
  } finally {
    clearTimeout(timeout);
  }
}

function requestBinaryWithElectronNet(url, options = {}) {
  return new Promise((resolve, reject) => {
    const request = electronNet.request({
      method: options.method || "GET",
      url,
    });
    const timeoutMs = options.timeoutMs || 30_000;
    let settled = false;
    const timeout = windowlessTimeout(() => {
      settled = true;
      request.abort();
      reject(new Error(`request timed out after ${timeoutMs}ms`));
    }, timeoutMs);

    for (const [name, value] of Object.entries(options.headers || {})) {
      if (value !== undefined && value !== null) {
        request.setHeader(name, String(value));
      }
    }

    request.on("response", (response) => {
      const chunks = [];
      response.on("data", (chunk) => chunks.push(Buffer.from(chunk)));
      response.on("end", () => {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timeout);
        resolve({
          statusCode: response.statusCode || 0,
          headers: response.headers || {},
          buffer: Buffer.concat(chunks),
        });
      });
      response.on("error", (error) => {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timeout);
        reject(error);
      });
    });

    request.on("error", (error) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timeout);
      reject(error);
    });

    if (options.body !== undefined && options.body !== null) {
      request.write(options.body);
    }
    request.end();
  });
}

function fallbackTracks() {
  return [
    {
      id: "loading-1",
      candidateId: "loading-1",
      title: "...",
      artist: "...",
      duration: 180,
      playbackUrl: "",
      source: "fallback",
    },
  ];
}

function windowlessTimeout(callback, ms) {
  return setTimeout(callback, ms);
}

function describeHttpFailure(label, response) {
  const contentType = getHeaderValue(response.headers, "content-type");
  const bodyText = /json|text|xml|html/i.test(contentType)
    ? response.buffer.toString("utf-8", 0, Math.min(response.buffer.length, 360)).trim()
    : "";
  return `${label} ${response.statusCode}${bodyText ? `: ${bodyText}` : ""}`;
}

function getHeaderValue(headers, targetName) {
  const target = targetName.toLowerCase();
  for (const [name, value] of Object.entries(headers || {})) {
    if (name.toLowerCase() !== target) {
      continue;
    }
    if (Array.isArray(value)) {
      return value.join(", ");
    }
    return String(value || "");
  }
  return "";
}

function isPlayableAudioBuffer(buffer, contentType) {
  if (!Buffer.isBuffer(buffer) || buffer.length < 32) {
    return false;
  }

  const firstByte = buffer[0];
  if (firstByte === 0x7b || firstByte === 0x5b || firstByte === 0x3c) {
    return false;
  }

  const normalizedType = String(contentType || "").toLowerCase();
  if (normalizedType.startsWith("audio/")) {
    return true;
  }

  const ascii = buffer.subarray(0, 12).toString("ascii");
  return (
    ascii.startsWith("ID3") ||
    ascii.startsWith("OggS") ||
    ascii.startsWith("RIFF") ||
    ascii.includes("ftyp") ||
    (buffer[0] === 0xff && (buffer[1] & 0xe0) === 0xe0)
  );
}

function inferAudioExtension(sourceUrl, contentType, buffer) {
  const normalizedType = String(contentType || "").toLowerCase();
  if (normalizedType.includes("mpeg") || normalizedType.includes("mp3")) {
    return "mp3";
  }
  if (normalizedType.includes("mp4") || normalizedType.includes("m4a")) {
    return "m4a";
  }
  if (normalizedType.includes("aac")) {
    return "aac";
  }
  if (normalizedType.includes("ogg")) {
    return "ogg";
  }
  if (normalizedType.includes("wav")) {
    return "wav";
  }
  if (normalizedType.includes("flac")) {
    return "flac";
  }

  try {
    const ext = path.extname(new URL(sourceUrl).pathname).replace(".", "").toLowerCase();
    if (["mp3", "m4a", "aac", "ogg", "wav", "flac"].includes(ext)) {
      return ext;
    }
  } catch {
    // Keep the default below.
  }

  const ascii = buffer.subarray(0, 12).toString("ascii");
  if (ascii.includes("ftyp")) {
    return "m4a";
  }
  if (ascii.startsWith("OggS")) {
    return "ogg";
  }
  if (ascii.startsWith("RIFF")) {
    return "wav";
  }
  return "mp3";
}

function sanitizeFilePart(value) {
  return String(value || "track")
    .replace(/[^a-zA-Z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80) || "track";
}

function isUsableFile(filePath) {
  try {
    const stats = fs.statSync(filePath);
    return stats.isFile() && stats.size > 1024;
  } catch {
    return false;
  }
}

function isHttpUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

function describeError(error) {
  if (!error || typeof error !== "object") {
    return String(error);
  }

  const message = typeof error.message === "string" ? error.message : String(error);
  const cause = error.cause;
  if (cause && typeof cause === "object") {
    const causeMessage = typeof cause.message === "string" ? cause.message : "";
    const causeCode = typeof cause.code === "string" ? cause.code : "";
    if (causeMessage && causeCode) {
      return `${message} (${causeCode}: ${causeMessage})`;
    }
    if (causeMessage) {
      return `${message} (${causeMessage})`;
    }
  }

  return message;
}

module.exports = {
  createDesktopApi,
};
