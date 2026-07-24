import path from "node:path";
import { fileURLToPath } from "node:url";
import { app } from "electron";
import { assertOfficialDataReady } from "../official/repository.js";
import { CapabilityStore } from "./capabilities.js";
import { registerIpcHandlers } from "./ipc.js";
import {
  APP_URL,
  registerAppProtocol,
  registerAppSchemePrivileges
} from "./protocol.js";
import { createVerifiedWindow } from "./startup.js";
import { createMainWindow } from "./window.js";

registerAppSchemePrivileges();
app.enableSandbox();

void app.whenReady().then(async () => {
  const mainDirectory = path.dirname(fileURLToPath(import.meta.url));
  const rendererRoot = path.resolve(mainDirectory, "../renderer");
  const resourceRoot = path.resolve(mainDirectory, "../../resources");
  const preload = path.resolve(mainDirectory, "../preload/index.js");
  await registerAppProtocol(rendererRoot);
  const mainWindow = await createVerifiedWindow(resourceRoot, {
    assertOfficialDataReady,
    createWindow: () => createMainWindow(preload)
  });
  registerIpcHandlers(mainWindow, new CapabilityStore());
  await mainWindow.loadURL(APP_URL);
});

app.on("window-all-closed", () => {
  app.quit();
});
