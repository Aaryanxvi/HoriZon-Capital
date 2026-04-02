const { app, BrowserWindow, ipcMain } = require("electron");
const path = require("path");
const { spawnBackend, killBackend } = require("./backend");
const { createTray } = require("./tray");

// Window control IPC (from preload → custom titlebar)
ipcMain.on("window-minimize", (e) => {
  BrowserWindow.fromWebContents(e.sender)?.minimize();
});
ipcMain.on("window-maximize", (e) => {
  const win = BrowserWindow.fromWebContents(e.sender);
  if (win) win.isMaximized() ? win.unmaximize() : win.maximize();
});
ipcMain.on("window-close", (e) => {
  BrowserWindow.fromWebContents(e.sender)?.close();
});

let mainWindow = null;
let tray = null;
let backendPort = null;

function createSplashWindow() {
  const splash = new BrowserWindow({
    width: 400,
    height: 300,
    frame: false,
    transparent: true,
    resizable: false,
    alwaysOnTop: true,
    webPreferences: { nodeIntegration: false, contextIsolation: true },
  });
  splash.loadFile(path.join(__dirname, "splash.html"));
  return splash;
}

function createMainWindow(port) {
  const win = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    title: "Horizon Capital",
    backgroundColor: "#080b11",
    show: false,
    frame: false,           // Frameless — custom titlebar in React
    titleBarStyle: "hidden", // macOS: hides titlebar but keeps traffic lights
    trafficLightPosition: { x: 12, y: 12 },
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  win.loadURL(`http://127.0.0.1:${port}`);

  win.once("ready-to-show", () => {
    win.show();
  });

  // Minimize to tray on close (unless quitting)
  win.on("close", (e) => {
    if (!app.isQuitting) {
      e.preventDefault();
      win.hide();
    }
  });

  return win;
}

app.whenReady().then(async () => {
  const splash = createSplashWindow();

  try {
    backendPort = await spawnBackend();
    mainWindow = createMainWindow(backendPort);

    mainWindow.once("ready-to-show", () => {
      splash.destroy();
    });

    // Fallback: close splash after 15s
    setTimeout(() => {
      if (!splash.isDestroyed()) splash.destroy();
    }, 15_000);

    tray = createTray(mainWindow);
  } catch (err) {
    console.error("Failed to start backend:", err);
    splash.destroy();
    app.quit();
  }
});

app.on("before-quit", () => {
  app.isQuitting = true;
  killBackend();
});

app.on("activate", () => {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.show();
  }
});

// Prevent multiple instances
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });
}
