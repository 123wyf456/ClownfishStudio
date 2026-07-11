import type { Station } from "@/radioData";

export type ApiSettings = {
  serverBaseUrl: string;
  agentProvider: "openai" | "anthropic";
  agentModel: string;
  agentApiKey: string;
  agentBaseUrl: string;
  openweatherApiKey: string;
  openweatherBaseUrl: string;
  weatherCity: string;
  neteaseApiBaseUrl: string;
  neteaseCookie: string;
  neteasePlaybackLevel: string;
  fishAudioApiKey: string;
  fishAudioBaseUrl: string;
  fishAudioVoiceId: string;
};

export type DeviceLocation = {
  latitude?: number;
  longitude?: number;
  cityHint?: string;
};

export type RuntimeItem = {
  provider: string;
  configured: boolean;
  mode: string;
};

export type RuntimeStatus = {
  agent: RuntimeItem;
  weather: RuntimeItem;
  music: RuntimeItem;
  tts: RuntimeItem;
};

export type ConfigResponse = {
  config: ApiSettings;
  runtime: RuntimeStatus;
};

export type DesktopBridgeConfigResponse = ConfigResponse & {
  local?: {
    serverBaseUrl?: string;
  };
};

export type GenerateStationResponse = {
  station: Station;
  runtime: RuntimeStatus;
  warnings: string[];
};

export type DesktopBridgeStationResponse = GenerateStationResponse;

export type PlayerAdvanceReason = "ended" | "next" | "previous" | "skip";

export type DesktopStationEvent = {
  id: string;
  type: string;
  payload?: Record<string, string | number | boolean | null | undefined>;
  createdAt?: string;
};

export const defaultSettings: ApiSettings = {
  serverBaseUrl: "http://127.0.0.1:8000",
  agentProvider: "openai",
  agentModel: "gpt-4o-mini",
  agentApiKey: "",
  agentBaseUrl: "https://api.openai.com/v1",
  openweatherApiKey: "",
  openweatherBaseUrl: "https://api.openweathermap.org",
  weatherCity: "",
  neteaseApiBaseUrl: "http://localhost:3000",
  neteaseCookie: "",
  neteasePlaybackLevel: "standard",
  fishAudioApiKey: "",
  fishAudioBaseUrl: "https://api.fish.audio",
  fishAudioVoiceId: "",
};
