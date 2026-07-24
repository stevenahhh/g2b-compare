import path from "node:path";
import { ipcMain, type BrowserWindow } from "electron";
import { parseNativeWorkbookInput } from "../../src/native/input.js";
import { writeNativeWorkbook } from "../../src/native/workbook.js";
import type { OfficialRepository } from "../../src/official/repository.js";
import { selectKoreaNetCandidate } from "../../src/official/selector.js";
import { OFFICIAL_DATA_REVISION } from "../../src/shared/contracts.js";
import type { CapabilityStore } from "../../src/main/capabilities.js";
import {
  ExportRequestSchema,
  ExportResponseSchema,
  IPC_CHANNELS,
  ReadSeedRequestSchema,
  ReadSeedResponseSchema
} from "../../src/main/ipc-contracts.js";
import {
  executeIpcBoundary,
  senderSnapshot
} from "../../src/main/ipc-boundary.js";
import { assertMainOwnedSelections } from "../../src/main/native-selection-authority.js";

export function replaceNativeFixtureHandlers(
  mainWindow: BrowserWindow,
  capabilities: CapabilityStore,
  repository: OfficialRepository
): void {
  ipcMain.removeHandler(IPC_CHANNELS.export);
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
          throw new TypeError("Native fixture received a legacy export");
        }
        const project = parseNativeWorkbookInput(parsed.project);
        assertMainOwnedSelections(project, repository);
        await writeNativeWorkbook(parsed.project, destination);
        return {
          workbookName: path.basename(destination),
          sheetCount: 6 as const
        };
      }
    })
  );

  ipcMain.removeHandler(IPC_CHANNELS.readSeed);
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
}
