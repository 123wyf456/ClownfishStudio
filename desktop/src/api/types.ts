import type { Station } from "@/radioData";

export type ApiSettings = {
  serverBaseUrl: string;
  agentProvider: "mock" | "openai" | "deepseek";
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

export type GenerateStationResponse = {
  station: Station;
  runtime: RuntimeStatus;
  warnings: string[];
};

export const defaultSettings: ApiSettings = {
  serverBaseUrl: "http://127.0.0.1:8000",
  agentProvider: "mock",
  agentModel: "deepseek-chat",
  agentApiKey: "",
  agentBaseUrl: "https://api.deepseek.com",
  openweatherApiKey: "",
  openweatherBaseUrl: "https://api.openweathermap.org",
  weatherCity: "Shanghai",
  neteaseApiBaseUrl: "http://localhost:3000",
  neteaseCookie: "",
  neteasePlaybackLevel: "standard",
  fishAudioApiKey: "",
  fishAudioBaseUrl: "https://api.fish.audio",
  fishAudioVoiceId: "",
};
