const { contextBridge, ipcRenderer } = require("electron");

// The only bridge into the main process: window chrome plus the backend port.
// Nothing here can read the filesystem or run a shell.
contextBridge.exposeInMainWorld("horizon", {
  platform: process.platform,
  isDesktop: true,
  minimize: () => ipcRenderer.send("window-minimize"),
  maximize: () => ipcRenderer.send("window-maximize"),
  close: () => ipcRenderer.send("window-close"),
  backendPort: () => ipcRenderer.invoke("backend-port"),
});
