/// <reference types="vite/client" />

interface Window {
  clownfishWindow?: {
    minimize: () => Promise<void>;
    close: () => Promise<void>;
  };
  clownfishApi?: {
    getConfig: () => Promise<unknown>;
    saveConfig: (payload: unknown) => Promise<unknown>;
    generateStation: (payload: unknown) => Promise<unknown>;
    chatStation: (payload: unknown) => Promise<unknown>;
  };
}
