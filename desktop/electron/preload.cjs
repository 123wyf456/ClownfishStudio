const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("clownfishWindow", {
  minimize: () => ipcRenderer.invoke("window:minimize"),
  close: () => ipcRenderer.invoke("window:close"),
});

contextBridge.exposeInMainWorld("clownfishRuntime", {
  platform: process.platform,
  isMac: process.platform === "darwin",
});

contextBridge.exposeInMainWorld("clownfishApi", {
  getConfig: () => ipcRenderer.invoke("api:get-config"),
  saveConfig: (payload) => ipcRenderer.invoke("api:save-config", payload),
  generateStation: (payload) => ipcRenderer.invoke("api:generate-station", payload),
  chatStation: (payload) => ipcRenderer.invoke("api:chat-station", payload),
  advancePlayer: (payload) => ipcRenderer.invoke("api:advance-player", payload),
});
