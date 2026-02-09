/**
 * Preload script — exposes safe IPC bridge to renderer
 */
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("soniaAPI", {
  getBackendWS: () => ipcRenderer.invoke("get-backend-ws"),
  minimize: () => ipcRenderer.invoke("window-minimize"),
  maximize: () => ipcRenderer.invoke("window-maximize"),
  close: () => ipcRenderer.invoke("window-close"),
});
