// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-2724B6DC758B
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
const { app, BrowserWindow, Menu, dialog, ipcMain, shell } = require("electron");
const path = require("path");
const fs = require("fs");

const { spawnBackend, killBackend } = require("./backend");
const { createTray } = require("./tray");

let mainWindow = null;
let tray = null;
let backendPort = null;

const STATE_FILE = path.join(app.getPath("userData"), "window-state.json");

function loadWindowState() {
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE, "utf8"));
  } catch {
    return { width: 1400, height: 900 };
  }
}

function saveWindowState(win) {
  if (!win || win.isDestroyed() || win.isMinimized()) return;
  const bounds = win.getBounds();
  try {
    fs.writeFileSync(STATE_FILE, JSON.stringify({ ...bounds, maximized: win.isMaximized() }));
  } catch {
    /* losing window position is not worth an error dialog */
  }
}

// --- Window control IPC (custom titlebar lives in React) ---------------------
ipcMain.on("window-minimize", (e) => BrowserWindow.fromWebContents(e.sender)?.minimize());
ipcMain.on("window-maximize", (e) => {
  const win = BrowserWindow.fromWebContents(e.sender);
  if (!win) return;
  win.isMaximized() ? win.unmaximize() : win.maximize();
});
ipcMain.on("window-close", (e) => BrowserWindow.fromWebContents(e.sender)?.close());
ipcMain.handle("backend-port", () => backendPort);

function createSplashWindow() {
  const splash = new BrowserWindow({
    width: 420,
    height: 300,
    frame: false,
    transparent: true,
    resizable: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true },
  });
  splash.loadFile(path.join(__dirname, "splash.html"));
  return splash;
}

function createMainWindow(port) {
  const state = loadWindowState();
  const win = new BrowserWindow({
    width: state.width ?? 1400,
    height: state.height ?? 900,
    x: state.x,
    y: state.y,
    minWidth: 1000,
    minHeight: 640,
    title: "Horizon Capital",
    backgroundColor: "#faf9f5",
    show: false,
    frame: false,
    titleBarStyle: "hidden",
    trafficLightPosition: { x: 12, y: 12 },
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webviewTag: false,
      spellcheck: false,
    },
  });

  if (state.maximized) win.maximize();
  win.loadURL(`http://127.0.0.1:${port}`);
  win.once("ready-to-show", () => win.show());

  // The renderer only ever talks to the local backend. Anything else is either a
  // mistake or hostile, so it opens in the user's browser instead of in-app.
  const isLocal = (url) => {
    try {
      const parsed = new URL(url);
      return parsed.hostname === "127.0.0.1" && parsed.port === String(port);
    } catch {
      return false;
    }
  };

  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });

  win.webContents.on("will-navigate", (event, url) => {
    if (!isLocal(url)) {
      event.preventDefault();
      if (/^https?:/.test(url)) shell.openExternal(url);
    }
  });

  win.webContents.on("render-process-gone", (_event, details) => {
    dialog.showErrorBox(
      "Horizon Capital",
      `The window crashed (${details.reason}). Reopening it from the tray will reload the UI; the engine kept running.`,
    );
  });

  ["resize", "move"].forEach((event) => win.on(event, () => saveWindowState(win)));

  // Close hides to tray so the agents keep trading; Quit really quits.
  win.on("close", (event) => {
    saveWindowState(win);
    if (!app.isQuitting) {
      event.preventDefault();
      win.hide();
    }
  });

  return win;
}

function buildMenu() {
  const template = [
    {
      label: "Horizon",
      submenu: [
        {
          label: "Reload UI",
          accelerator: "CmdOrCtrl+R",
          click: () => mainWindow?.webContents.reload(),
        },
        {
          label: "Toggle Developer Tools",
          accelerator: process.platform === "darwin" ? "Alt+Cmd+I" : "Ctrl+Shift+I",
          click: () => mainWindow?.webContents.toggleDevTools(),
        },
        { type: "separator" },
        {
          label: "Quit",
          accelerator: "CmdOrCtrl+Q",
          click: () => {
            app.isQuitting = true;
            app.quit();
          },
        },
      ],
    },
    {
      label: "Edit",
      submenu: [
        { role: "undo" },
        { role: "redo" },
        { type: "separator" },
        { role: "cut" },
        { role: "copy" },
        { role: "paste" },
        { role: "selectAll" },
      ],
    },
    {
      label: "View",
      submenu: [
        { role: "resetZoom" },
        { role: "zoomIn" },
        { role: "zoomOut" },
        { type: "separator" },
        { role: "togglefullscreen" },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// Only one instance may own the SQLite database and the trading loop.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  });

  app.whenReady().then(async () => {
    buildMenu();
    const splash = createSplashWindow();

    try {
      backendPort = await spawnBackend();
      mainWindow = createMainWindow(backendPort);
      mainWindow.once("ready-to-show", () => {
        if (!splash.isDestroyed()) splash.destroy();
      });
      // Fallback: never leave the splash stuck in front of a live window.
      setTimeout(() => {
        if (!splash.isDestroyed()) splash.destroy();
      }, 20_000);

      tray = createTray(mainWindow);
    } catch (err) {
      if (!splash.isDestroyed()) splash.destroy();
      dialog.showErrorBox(
        "Horizon Capital could not start",
        `${err.message}\n\nCheck that the backend dependencies are installed:\n` +
          `  cd backend && pip install -r requirements.txt`,
      );
      app.isQuitting = true;
      killBackend();
      app.quit();
    }
  });
}

app.on("before-quit", () => {
  app.isQuitting = true;
  killBackend();
});

app.on("window-all-closed", () => {
  // Windows/Linux: the tray keeps the app alive, matching the terminal agent
  // which also runs until you tell it to stop.
  if (process.platform !== "darwin" && app.isQuitting) app.quit();
});

app.on("activate", () => {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.show();
});

process.on("exit", killBackend);
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token 2724B6DC758B - verify with scripts/authorship.py verify
