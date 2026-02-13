/**
 * Sonia Avatar — Electron Main Process
 * v2.6 Track C
 *
 * Hosts the React+Three.js avatar UI in an Electron window.
 * Connects to the backend via local WebSocket for:
 *   - Conversation state
 *   - Speaking state + viseme stream
 *   - Emotion tags
 *   - Privacy/mic/cam toggles
 */

const { app, BrowserWindow, ipcMain } = require("electron");
const path = require("path");

const BACKEND_WS = "ws://127.0.0.1:7000/v1/ui/stream";
const DEV_URL = "http://localhost:5173";
const IS_DEV = process.env.NODE_ENV === "development" || !app.isPackaged;

let mainWindow = null;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 480,
    height: 720,
    minWidth: 360,
    minHeight: 540,
    frame: false,
    transparent: false,
    backgroundColor: "#0a0a0a",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
    titleBarStyle: "hidden",
    titleBarOverlay: {
      color: "#0a0a0a",
      symbolColor: "#cc3333",
      height: 32,
    },
  });

  if (IS_DEV) {
    mainWindow.loadURL(DEV_URL);
    mainWindow.webContents.openDevTools({ mode: "detach" });
  } else {
    mainWindow.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  }

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

// --- IPC handlers ---

ipcMain.handle("get-backend-ws", () => BACKEND_WS);

ipcMain.handle("window-minimize", () => mainWindow?.minimize());
ipcMain.handle("window-maximize", () => {
  if (mainWindow?.isMaximized()) {
    mainWindow.unmaximize();
  } else {
    mainWindow?.maximize();
  }
});
ipcMain.handle("window-close", () => mainWindow?.close());

// --- App lifecycle ---

app.whenReady().then(createWindow);

app.on("window-all-closed", () => {
  app.quit();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});
