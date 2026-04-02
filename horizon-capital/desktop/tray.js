const { Tray, Menu, nativeImage } = require("electron");
const path = require("path");

let tray = null;

function createTray(mainWindow) {
  // Use a simple 16x16 icon; fall back to empty image if missing
  const iconPath = path.join(__dirname, "icons", "icon.ico");
  let icon;
  try {
    icon = nativeImage.createFromPath(iconPath);
    if (icon.isEmpty()) icon = nativeImage.createEmpty();
  } catch {
    icon = nativeImage.createEmpty();
  }

  tray = new Tray(icon);
  tray.setToolTip("Horizon Capital");

  const contextMenu = Menu.buildFromTemplate([
    {
      label: "Show",
      click: () => {
        mainWindow.show();
        mainWindow.focus();
      },
    },
    {
      label: "Hide",
      click: () => mainWindow.hide(),
    },
    { type: "separator" },
    {
      label: "Quit",
      click: () => {
        const { app } = require("electron");
        app.isQuitting = true;
        app.quit();
      },
    },
  ]);

  tray.setContextMenu(contextMenu);

  tray.on("click", () => {
    if (mainWindow.isVisible()) {
      mainWindow.hide();
    } else {
      mainWindow.show();
      mainWindow.focus();
    }
  });

  return tray;
}

module.exports = { createTray };
