import {
  defaultSettings,
  type ConfigResponse,
  type DesktopBridgeConfigResponse,
  type DesktopBridgeStationResponse,
  type DeviceLocation,
  type GenerateStationResponse,
  type PlayerAdvanceReason,
} from "@/api/types";

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function normalizeAgentProvider(
  value: unknown,
  fallback: ConfigResponse["config"]["agentProvider"] = defaultSettings.agentProvider,
): ConfigResponse["config"]["agentProvider"] {
  if (value === "anthropic") {
    return "anthropic";
  }
  if (value === "openai") {
    return "openai";
  }
  return fallback;
}

function agentApiKeyFromConfig(
  config: Record<string, unknown>,
  provider: ConfigResponse["config"]["agentProvider"],
  fallback: string,
): string {
  if (provider === "anthropic") {
    return typeof config.anthropic_api_key === "string" ? config.anthropic_api_key : fallback;
  }
  if (typeof config.openai_api_key === "string" && config.openai_api_key) {
    return config.openai_api_key;
  }
  return fallback;
}

function agentBaseUrlFromConfig(
  config: Record<string, unknown>,
  provider: ConfigResponse["config"]["agentProvider"],
  fallback: string,
): string {
  if (provider === "anthropic") {
    return typeof config.anthropic_base_url === "string" && config.anthropic_base_url
      ? config.anthropic_base_url
      : "https://api.anthropic.com";
  }
  if (typeof config.openai_base_url === "string" && config.openai_base_url) {
    return config.openai_base_url;
  }
  return fallback;
}

export async function loadConfig(): Promise<ConfigResponse> {
  const response = await window.clownfishApi?.getConfig();
  if (!isObject(response)) {
    return {
      config: defaultSettings,
      runtime: mockRuntime(),
    };
  }

  const remoteConfig: Record<string, unknown> = isObject(response.config) ? response.config : {};
  const localConfig: Record<string, unknown> = isObject(response.local) ? response.local : {};

  return {
    config: {
      ...defaultSettings,
      serverBaseUrl:
        typeof localConfig.serverBaseUrl === "string"
          ? localConfig.serverBaseUrl
          : defaultSettings.serverBaseUrl,
      agentProvider: normalizeAgentProvider(remoteConfig.radio_agent_provider),
      agentModel:
        typeof remoteConfig.radio_agent_model === "string"
          ? remoteConfig.radio_agent_model
          : defaultSettings.agentModel,
      agentApiKey: agentApiKeyFromConfig(remoteConfig, normalizeAgentProvider(remoteConfig.radio_agent_provider), ""),
      agentBaseUrl: agentBaseUrlFromConfig(remoteConfig, normalizeAgentProvider(remoteConfig.radio_agent_provider), defaultSettings.agentBaseUrl),
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
  deviceLocation?: DeviceLocation | null;
  message?: string;
}): Promise<GenerateStationResponse | null> {
  const response = await window.clownfishApi?.generateStation(payload);
  return normalizeStationResponse(response);
}

export async function chatStation(payload: {
  deviceLocation?: DeviceLocation | null;
  message: string;
}): Promise<GenerateStationResponse | null> {
  const response = await window.clownfishApi?.chatStation(payload);
  return normalizeStationResponse(response);
}

export async function advancePlayer(payload: {
  itemId?: string;
  reason: PlayerAdvanceReason;
}): Promise<GenerateStationResponse | null> {
  const response = await window.clownfishApi?.advancePlayer(payload);
  return normalizeStationResponse(response);
}

function loadConfigFromResponse(
  response: DesktopBridgeConfigResponse | Record<string, unknown>,
  fallback: ConfigResponse["config"],
): ConfigResponse {
  const runtime = normalizeRuntime(response.runtime);
  const remoteConfig: Record<string, unknown> = isObject(response.config) ? response.config : {};
  const localConfig: Record<string, unknown> = isObject(response.local) ? response.local : {};

  return {
    config: {
      ...fallback,
      serverBaseUrl:
        typeof localConfig.serverBaseUrl === "string"
          ? localConfig.serverBaseUrl
          : fallback.serverBaseUrl,
      agentProvider: normalizeAgentProvider(remoteConfig.radio_agent_provider, fallback.agentProvider),
      agentModel:
        typeof remoteConfig.radio_agent_model === "string"
          ? remoteConfig.radio_agent_model
          : fallback.agentModel,
      agentApiKey: agentApiKeyFromConfig(
        remoteConfig,
        normalizeAgentProvider(remoteConfig.radio_agent_provider, fallback.agentProvider),
        fallback.agentApiKey,
      ),
      agentBaseUrl: agentBaseUrlFromConfig(
        remoteConfig,
        normalizeAgentProvider(remoteConfig.radio_agent_provider, fallback.agentProvider),
        fallback.agentBaseUrl,
      ),
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

function normalizeStationResponse(
  value: DesktopBridgeStationResponse | null | undefined,
): GenerateStationResponse | null {
  if (!value || !value.station) {
    return null;
  }
  return value;
}

function mockRuntime(): ConfigResponse["runtime"] {
  return {
    agent: { provider: "openai", configured: false, mode: "not_configured" },
    weather: { provider: "disabled", configured: false, mode: "disabled" },
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
