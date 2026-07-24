import {
  ATOMIC_EXPORT_ERROR_MESSAGES,
  type AtomicCleanupReceipt,
  type AtomicExportErrorCode,
  type AtomicLegacyExportFailure,
  type AtomicLegacyExportRequest,
  type AtomicLegacyExportSuccess
} from "./types.js";
import type { PublicationState } from "./files.js";

export function exportSuccess(input: {
  readonly request: AtomicLegacyExportRequest;
  readonly workbookName: string;
  readonly validationReportName: string;
  readonly workbookSha256: string;
  readonly validationReportSha256: string;
  readonly cleanup: AtomicCleanupReceipt;
}): AtomicLegacyExportSuccess {
  return {
    ok: true,
    workbookName: input.workbookName,
    validationReportName: input.validationReportName,
    sourceSha256: input.request.expectedSourceSha256,
    workbookSha256: input.workbookSha256,
    validationReportSha256: input.validationReportSha256,
    cleanup: input.cleanup
  };
}

export function exportFailure(
  code: AtomicExportErrorCode,
  cleanup: AtomicCleanupReceipt
): AtomicLegacyExportFailure {
  return {
    ok: false,
    error: { code, message: ATOMIC_EXPORT_ERROR_MESSAGES[code] },
    cleanup
  };
}

export function cleanupReceipt(
  state: PublicationState
): AtomicCleanupReceipt {
  return {
    temporaryFilesCreated: state.temporaryFilesCreated,
    temporaryFilesRemoved: state.temporaryFilesRemoved,
    finalFilesPublished: state.finalFilesPublished,
    finalFilesRolledBack: state.finalFilesRolledBack,
    complete: state.cleanupComplete
  };
}
