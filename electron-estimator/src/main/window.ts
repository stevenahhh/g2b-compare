import {
  BrowserWindow,
  type BrowserWindowConstructorOptions
} from "electron";

const SECURE_WEB_PREFERENCES = {
  sandbox: true,
  contextIsolation: true,
  nodeIntegration: false,
  nodeIntegrationInWorker: false,
  nodeIntegrationInSubFrames: false,
  webviewTag: false,
  webSecurity: true,
  allowRunningInsecureContent: false
} as const;

export function createMainWindowOptions(
  preload: string
): BrowserWindowConstructorOptions {
  return {
    width: 1440,
    height: 900,
    autoHideMenuBar: true,
    webPreferences: {
      ...SECURE_WEB_PREFERENCES,
      preload
    }
  };
}

export function createMainWindow(preload: string): BrowserWindow {
  const mainWindow = new BrowserWindow(createMainWindowOptions(preload));
  const { webContents } = mainWindow;
  webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  webContents.on("will-navigate", (event) => {
    event.preventDefault();
  });
  webContents.on("will-frame-navigate", (event) => {
    event.preventDefault();
  });
  webContents.on("will-redirect", (event) => {
    event.preventDefault();
  });
  webContents.on("will-attach-webview", (event) => {
    event.preventDefault();
  });
  webContents.session.setPermissionCheckHandler(() => false);
  webContents.session.setPermissionRequestHandler(
    (_requestingContents, _permission, callback) => {
      callback(false);
    }
  );
  webContents.session.on("will-download", (event) => {
    event.preventDefault();
  });
  return mainWindow;
}
