import path from "node:path";
import { fileURLToPath } from "node:url";
import { app } from "electron";
import {
  assertOfficialDataReady,
  loadOfficialRepository
} from "../../src/official/repository.js";
import { CapabilityStore } from "../../src/main/capabilities.js";
import { registerIpcHandlers } from "../../src/main/ipc.js";
import {
  APP_URL,
  registerAppProtocol,
  registerAppSchemePrivileges
} from "../../src/main/protocol.js";
import { createVerifiedWindow } from "../../src/main/startup.js";
import { createMainWindow } from "../../src/main/window.js";
import { trustedCandidateFixtures } from "./native-workflow.fixtures.js";
import { replaceNativeFixtureHandlers } from "./native-workflow-test-ipc.js";

registerAppSchemePrivileges();
app.enableSandbox();

void app.whenReady().then(async () => {
  const mainDirectory = path.dirname(fileURLToPath(import.meta.url));
  const projectRoot = path.resolve(mainDirectory, "../..");
  const rendererRoot = path.resolve(projectRoot, "dist/renderer");
  const resourceRoot = path.resolve(projectRoot, "resources");
  const preload = path.resolve(projectRoot, "dist/preload/index.js");
  await registerAppProtocol(rendererRoot);
  const mainWindow = await createVerifiedWindow(resourceRoot, {
    assertOfficialDataReady,
    createWindow: () => createMainWindow(preload)
  });
  const capabilities = new CapabilityStore();
  registerIpcHandlers(mainWindow, capabilities);
  const repository = await loadOfficialRepository({
    rootPath: resourceRoot
  });
  replaceNativeFixtureHandlers(
    mainWindow,
    capabilities,
    Object.freeze({
      ...repository,
      sourcedProducts: trustedCandidateFixtures
    })
  );
  await mainWindow.loadURL(APP_URL);
});

app.on("window-all-closed", () => {
  app.quit();
});
