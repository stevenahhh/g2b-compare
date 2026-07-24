import type {
  BridgeErrorCode,
  DialogRequest,
  ExportRequest,
  ImportRequest,
  ReadSeedRequest
} from "../main/ipc-contracts.js";
import type {
  LegacyWorkflowErrorCode
} from "../workflows/legacy/contracts.js";
import type {
  NativeCatalog,
  NativeSelectionResult
} from "../workflows/native/contracts.js";

type BridgeResult<T> =
  | { readonly ok: true; readonly value: T }
  | {
      readonly ok: false;
      readonly error: { readonly code: BridgeErrorCode; readonly message: string };
    };

type SeedInfo = {
  readonly datasetVersion: string;
  readonly compositeSha256: string;
  readonly sourceManifestSha256: string;
};

declare global {
  interface Window {
    readonly estimator: {
      readonly dialog: (request: DialogRequest) => Promise<
        BridgeResult<
          | { readonly cancelled: true }
          | {
              readonly cancelled: false;
              readonly capabilityId: string;
              readonly name: string;
            }
        >
      >;
      readonly import: (request: ImportRequest) => Promise<BridgeResult<unknown>>;
      readonly export: (request: ExportRequest) => Promise<
        BridgeResult<
          | {
              readonly workbookName: string;
              readonly validationReportName: string;
            }
          | {
              readonly errorCode: LegacyWorkflowErrorCode;
              readonly message: string;
              readonly finalFilesPublished: 0;
            }
          | { readonly workbookName: string; readonly sheetCount: 6 }
        >
      >;
      readonly readSeed: (
        request?: ReadSeedRequest
      ) => Promise<
        BridgeResult<SeedInfo | NativeCatalog | NativeSelectionResult>
      >;
      readonly getBuildInfo: () => Promise<
        BridgeResult<{
          readonly appVersion: string;
          readonly electronVersion: string;
          readonly chromeVersion: string;
          readonly unsigned: true;
          readonly sandboxed: true;
          readonly contextIsolated: true;
        }>
      >;
    };
  }
}
