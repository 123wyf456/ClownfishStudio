import { defaultSettings, type ConfigResponse, type GenerateStationResponse } from "@/api/types";

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export async function loadConfig(): Promise<ConfigResponse> {
  const response = await window.clownfishApi?.getConfig();
  if (!isObject(response)) {
    return {
      config: defaultSettings,
      runtime: mockRuntime(),
    };
  }

  const remoteConfig = isObject(response.config) ? response.config : {};
  const localConfig = isObject(response.local) ? response.local : {};

  return {
    config: {
      ...defaultSettings,
      serverBaseUrl:
        typeof localConfig.serverBaseUrl === "string"
          ? localConfig.serverBaseUrl
          : defaultSettings.serverBaseUrl,
      agentProvider:
        (typeof remoteConfig.radio_agent_provider === "string"
          ? remoteConfig.radio_agent_provider
          : defaultSettings.agentProvider) as ConfigResponse["config"]["agentProvider"],
      agentModel:
        typeof remoteConfig.radio_agent_model === "string"
          ? remoteConfig.radio_agent_model
          : defaultSettings.agentModel,
      agentApiKey:
        typeof remoteConfig.deepseek_api_key === "string" && remoteConfig.deepseek_api_key
          ? remoteConfig.deepseek_api_key
          : typeof remoteConfig.openai_api_key === "string"
            ? remoteConfig.openai_api_key
            : "",
      agentBaseUrl:
        typeof remoteConfig.deepseek_base_url === "string" && remoteConfig.deepseek_base_url
          ? remoteConfig.deepseek_base_url
          : typeof remoteConfig.openai_base_url === "string"
            ? remoteConfig.openai_base_url
            : defaultSettings.agentBaseUrl,
      openweatherApiKey:
        typeof remoteConfig.openweather_api_key === "string"
          ? remoteConfig.openweather_api_key
          : "",
      openweatherBaseUrl:
        typeof remoteConfig.openweather_base_url === "string"
          ? remoteConfig.openweather_base_url
          : defaultSettings.openweatherBaseUrl,
      weatherCity: defaultSettings.weatherCity,
      neteaseApiBaseUrl:
        typeof remoteConfig.netease_api_base_url === "string"
          ? remoteConfig.netease_api_base_url
          : defaultSettings.neteaseApiBaseUrl,
      neteaseCookie:
        typeof remoteConfig.netease_cookie === "string" ? remoteConfig.netease_cookie : "",
      neteasePlaybackLevel:
        typeof remoteConfig.netease_playback_level === "string"
          ? remoteConfig.netease_playback_level
          : defaultSettings.neteasePlaybackLevel,
      fishAudioApiKey:
        typeof remoteConfig.fish_audio_api_key === "string"
          ? remoteConfig.fish_audio_api_key
          : "",
      fishAudioBaseUrl:
        typeof remoteConfig.fish_audio_base_url === "string"
          ? remoteConfig.fish_audio_base_url
          : defaultSettings.fishAudioBaseUrl,
      fishAudioVoiceId:
        typeof remoteConfig.fish_audio_voice_id === "string"
          ? remoteConfig.fish_audio_voice_id
          : "",
    },
    runtime: normalizeRuntime(response.runtime),
  };
}

export async function saveConfig(config: ConfigResponse["config"]): Promise<ConfigResponse> {
  const response = await window.clownfishApi?.saveConfig(config);
  if (!isObject(response)) {
    return { config, runtime: mockRuntime() };
  }

  return loadConfigFromResponse(response, config);
}

export async function generateStation(payload: {
  city?: string;
  message?: string;
}): Promise<GenerateStationResponse | null> {
  const response = await window.clownfishApi?.generateStation(payload);
  return isObject(response) ? (response as GenerateStationResponse) : null;
}

export async function chatStation(payload: {
  city?: string;
  message: string;
}): Promise<GenerateStationResponse | null> {
  const response = await window.clownfishApi?.chatStation(payload);
  return isObject(response) ? (response as GenerateStationResponse) : null;
}

function loadConfigFromResponse(response: Record<string, unknown>, fallback: ConfigResponse["config"]): ConfigResponse {
  const runtime = normalizeRuntime(response.runtime);
  const remoteConfig = isObject(response.config) ? response.config : {};
  const localConfig = isObject(response.local) ? response.local : {};

  return {
    config: {
      ...fallback,
      serverBaseUrl:
        typeof localConfig.serverBaseUrl === "string"
          ? localConfig.serverBaseUrl
          : fallback.serverBaseUrl,
      agentProvider:
        (typeof remoteConfig.radio_agent_provider === "string"
          ? remoteConfig.radio_agent_provider
          : fallback.agentProvider) as ConfigResponse["config"]["agentProvider"],
      agentModel:
        typeof remoteConfig.radio_agent_model === "string"
          ? remoteConfig.radio_agent_model
          : fallback.agentModel,
      agentApiKey:
        typeof remoteConfig.deepseek_api_key === "string" && remoteConfig.deepseek_api_key
          ? remoteConfig.deepseek_api_key
          : typeof remoteConfig.openai_api_key === "string"
            ? remoteConfig.openai_api_key
            : fallback.agentApiKey,
      agentBaseUrl:
        typeof remoteConfig.deepseek_base_url === "string" && remoteConfig.deepseek_base_url
          ? remoteConfig.deepseek_base_url
          : typeof remoteConfig.openai_base_url === "string"
            ? remoteConfig.openai_base_url
            : fallback.agentBaseUrl,
      openweatherApiKey:
        typeof remoteConfig.openweather_api_key === "string"
          ? remoteConfig.openweather_api_key
          : fallback.openweatherApiKey,
      openweatherBaseUrl:
        typeof remoteConfig.openweather_base_url === "string"
          ? remoteConfig.openweather_base_url
          : fallback.openweatherBaseUrl,
      weatherCity: fallback.weatherCity,
      neteaseApiBaseUrl:
        typeof remoteConfig.netease_api_base_url === "string"
          ? remoteConfig.netease_api_base_url
          : fallback.neteaseApiBaseUrl,
      neteaseCookie:
        typeof remoteConfig.netease_cookie === "string"
          ? remoteConfig.netease_cookie
          : fallback.neteaseCookie,
      neteasePlaybackLevel:
        typeof remoteConfig.netease_playback_level === "string"
          ? remoteConfig.netease_playback_level
          : fallback.neteasePlaybackLevel,
      fishAudioApiKey:
        typeof remoteConfig.fish_audio_api_key === "string"
          ? remoteConfig.fish_audio_api_key
          : fallback.fishAudioApiKey,
      fishAudioBaseUrl:
        typeof remoteConfig.fish_audio_base_url === "string"
          ? remoteConfig.fish_audio_base_url
          : fallback.fishAudioBaseUrl,
      fishAudioVoiceId:
        typeof remoteConfig.fish_audio_voice_id === "string"
          ? remoteConfig.fish_audio_voice_id
          : fallback.fishAudioVoiceId,
    },
    runtime,
  };
}

function mockRuntime(): ConfigResponse["runtime"] {
  return {
    agent: { provider: "mock", configured: true, mode: "mock" },
    weather: { provider: "openweather", configured: false, mode: "mock" },
    music: { provider: "netease_cloud_music", configured: false, mode: "mock" },
    tts: { provider: "fish_audio", configured: false, mode: "mock" },
  };
}

function normalizeRuntime(value: unknown): ConfigResponse["runtime"] {
  if (!isObject(value)) {
    return mockRuntime();
  }

  const runtime = value as Record<string, unknown>;
  const agentCandidate = isObject(runtime.agent)
    ? runtime.agent
    : isObject(runtime.brain)
      ? runtime.brain
      : null;
  const weatherCandidate = isObject(runtime.weather) ? runtime.weather : null;
  const musicCandidate = isObject(runtime.music) ? runtime.music : null;
  const ttsCandidate = isObject(runtime.tts) ? runtime.tts : null;

  return {
    agent: normalizeRuntimeItem(
      agentCandidate,
      mockRuntime().agent,
    ),
    weather: normalizeRuntimeItem(
      weatherCandidate,
      mockRuntime().weather,
    ),
    music: normalizeRuntimeItem(
      musicCandidate,
      mockRuntime().music,
    ),
    tts: normalizeRuntimeItem(
      ttsCandidate,
      mockRuntime().tts,
    ),
  };
}

function normalizeRuntimeItem(
  value: Record<string, unknown> | null,
  fallback: ConfigResponse["runtime"]["agent"],
): ConfigResponse["runtime"]["agent"] {
  if (!value) {
    return fallback;
  }

  return {
    provider:
      typeof value.provider === "string" && value.provider
        ? value.provider
        : fallback.provider,
    configured:
      typeof value.configured === "boolean" ? value.configured : fallback.configured,
    mode:
      typeof value.mode === "string" && value.mode
        ? value.mode
        : fallback.mode,
  };
}
