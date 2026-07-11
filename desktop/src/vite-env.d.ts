/// <reference types="vite/client" />

import type {
  ApiSettings,
  DesktopBridgeConfigResponse,
  DesktopBridgeStationResponse,
  DeviceLocation,
  PlayerAdvanceReason,
} from "@/api/types";

declare global {
  interface Window {
    clownfishWindow?: {
      minimize: () => Promise<void>;
      close: () => Promise<void>;
    };
    clownfishRuntime?: {
      platform: string;
      isMac: boolean;
    };
    clownfishApi?: {
      getConfig: () => Promise<DesktopBridgeConfigResponse | null>;
      saveConfig: (payload: ApiSettings) => Promise<DesktopBridgeConfigResponse | null>;
      generateStation: (payload: {
        deviceLocation?: DeviceLocation | null;
        message?: string;
      }) => Promise<DesktopBridgeStationResponse | null>;
      chatStation: (payload: {
        deviceLocation?: DeviceLocation | null;
        message: string;
      }) => Promise<DesktopBridgeStationResponse | null>;
      advancePlayer: (payload: {
        itemId?: string;
        reason: PlayerAdvanceReason;
      }) => Promise<DesktopBridgeStationResponse | null>;
    };
  }
}

export {};
