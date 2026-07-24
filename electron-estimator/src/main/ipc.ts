import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import {
  app,
  dialog,
  ipcMain,
  type BrowserWindow
} from "electron";
import { importLegacyWorkbook } from "../legacy/import.js";
import { parseNativeWorkbookInput } from "../native/input.js";
import { writeNativeWorkbook } from "../native/workbook.js";
import { loadOfficialRepository } from "../official/repository.js";
import { selectKoreaNetCandidate } from "../official/selector.js";
import { OFFICIAL_DATA_REVISION } from "../shared/contracts.js";
import type { CapabilityStore, FrameIdentity } from "./capabilities.js";
import {
  BuildInfoRequestSchema,
  DialogRequestSchema,
  DialogResponseSchema,
  ExportRequestSchema,
  ExportResponseSchema,
  IPC_CHANNELS,
  ImportRequestSchema,
  ImportResponseSchema,
  MainBuildInfoResponseSchema,
  ReadSeedRequestSchema,
  ReadSeedResponseSchema,
  type DialogRequest
} from "./ipc-contracts.js";
import {
  executeIpcBoundary,
  OperationUnavailableError,
  senderSnapshot
} from "./ipc-boundary.js";
import { assertMainOwnedSelections } from "./native-selection-authority.js";
import {
  exportLegacySession,
  LegacySessionStore
} from "./legacy-session.js";

export { IPC_CHANNELS } from "./ipc-contracts.js";
export {
  executeIpcBoundary,
  type SenderSnapshot
} from "./ipc-boundary.js";

export function registerIpcHandlers(
  mainWindow: BrowserWindow,
  capabilities: CapabilityStore
): void {
  const legacySessions = new LegacySessionStore();
  const legacyManifestRoot = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    "../../resources/manifests/legacy"
  );
  ipcMain.handle(IPC_CHANNELS.dialog, (event, request: unknown) =>
    executeIpcBoundary({
      sender: senderSnapshot(event, mainWindow),
      request,
      requestSchema: DialogRequestSchema,
      responseSchema: DialogResponseSchema,
      operation: (parsed, frame) =>
        chooseFile({
          mainWindow,
          capabilities,
          request: parsed,
          frame
        })
    })
  );
  ipcMain.handle(IPC_CHANNELS.import, (event, request: unknown) =>
    executeIpcBoundary({
      sender: senderSnapshot(event, mainWindow),
      request,
      requestSchema: ImportRequestSchema,
      responseSchema: ImportResponseSchema,
      operation: async (parsed, frame) => {
        const sourcePath = capabilities.consume({
          capabilityId: parsed.capabilityId,
          kind: "import",
          frame
        });
        const imported = await importLegacyWorkbook(sourcePath, {
          manifestRoot: pathToFileURL(`${legacyManifestRoot}${path.sep}`)
        });
        return legacySessions.create({
          sourcePath,
          sourceName: path.basename(sourcePath),
          imported,
          frame
        });
      }
    })
  );
  ipcMain.handle(IPC_CHANNELS.export, (event, request: unknown) =>
    executeIpcBoundary({
      sender: senderSnapshot(event, mainWindow),
      request,
      requestSchema: ExportRequestSchema,
      responseSchema: ExportResponseSchema,
      operation: async (parsed, frame) => {
        const destination = capabilities.consume({
          capabilityId: parsed.capabilityId,
          kind: "export",
          frame
        });
        if (!("kind" in parsed)) {
          throw new OperationUnavailableError();
        }
        switch (parsed.kind) {
          case "native_workbook": {
            const repository = await loadOfficialRepository();
            const project = parseNativeWorkbookInput(parsed.project);
            assertMainOwnedSelections(project, repository);
            await writeNativeWorkbook(parsed.project, destination);
            return {
              workbookName: path.basename(destination),
              sheetCount: 6 as const
            };
          }
          case "legacy_workbook":
            return exportLegacySession({
              request: parsed,
              destination,
              stored: legacySessions.get(parsed.sessionId, frame),
              dependencies: {
                appVersion: app.getVersion(),
                manifestRoot: legacyManifestRoot
              }
            });
          default:
            return assertNever(parsed);
        }
      }
    })
  );
  ipcMain.handle(IPC_CHANNELS.readSeed, (event, request: unknown) =>
    executeIpcBoundary({
      sender: senderSnapshot(event, mainWindow),
      request,
      requestSchema: ReadSeedRequestSchema,
      responseSchema: ReadSeedResponseSchema,
      operation: async (parsed) => {
        if (!("kind" in parsed)) {
          return OFFICIAL_DATA_REVISION;
        }
        const repository = await loadOfficialRepository();
        if (parsed.kind === "native_select") {
          return selectKoreaNetCandidate({
            requestedItemKey: parsed.requestedItemKey,
            specification: parsed.specification,
            unit: parsed.unit,
            candidates: repository.sourcedProducts
          });
        }
        return {
          revision: {
            datasetVersion: repository.revision.datasetVersion,
            compositeSha256: repository.revision.compositeSha256,
            sourceManifestSha256:
              repository.revision.sourceManifestSha256
          },
          marketPrices: repository.marketPrices,
          productivity: repository.productivity,
          wages: repository.wages,
          sourcedProducts: repository.sourcedProducts
        };
      }
    })
  );
  ipcMain.handle(IPC_CHANNELS.getBuildInfo, (event, request: unknown) =>
    executeIpcBoundary({
      sender: senderSnapshot(event, mainWindow),
      request,
      requestSchema: BuildInfoRequestSchema,
      responseSchema: MainBuildInfoResponseSchema,
      operation: async () => ({
        appVersion: app.getVersion(),
        electronVersion: process.versions.electron ?? "unknown",
        chromeVersion: process.versions.chrome ?? "unknown",
        unsigned: true
      })
    })
  );
}

type DialogSelection = {
  readonly mainWindow: BrowserWindow;
  readonly capabilities: CapabilityStore;
  readonly request: DialogRequest;
  readonly frame: FrameIdentity;
};

async function chooseFile(selection: DialogSelection): Promise<unknown> {
  const { mainWindow, capabilities, request, frame } = selection;
  switch (request.kind) {
    case "import": {
      const result = await dialog.showOpenDialog(mainWindow, {
        properties: ["openFile"],
        filters: [
          {
            name: "Excel 통합 문서",
            extensions: ["xlsx", "xlsm"]
          }
        ]
      });
      const selectedPath = result.filePaths[0];
      if (result.canceled || selectedPath === undefined) {
        return { cancelled: true };
      }
      return {
        cancelled: false,
        capabilityId: capabilities.issue("import", selectedPath, frame),
        name: path.basename(selectedPath)
      };
    }
    case "export":
    case "legacy_export": {
      const result = await dialog.showSaveDialog(mainWindow, {
        defaultPath:
          request.kind === "legacy_export"
            ? "견적_검토초안_미재계산.xlsx"
            : "견적.xlsx",
        filters: [{ name: "Excel 통합 문서", extensions: ["xlsx"] }]
      });
      if (result.canceled || result.filePath === undefined) {
        return { cancelled: true };
      }
      return {
        cancelled: false,
        capabilityId: capabilities.issue("export", result.filePath, frame),
        name: path.basename(result.filePath)
      };
    }
    default:
      return assertNever(request.kind);
  }
}

function assertNever(value: never): never {
  throw new TypeError(`Unexpected dialog kind: ${String(value)}`);
}
