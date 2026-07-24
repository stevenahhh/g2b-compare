export const VALIDATION_ERROR_CODES = [
  "INVALID_REPORT_INPUT",
  "MALFORMED_ZIP",
  "TEMPLATE_HASH_MISMATCH",
  "STALE_MANIFEST",
  "PATCH_RECEIPT_MISMATCH",
  "UNEXPECTED_PART_DRIFT",
  "UNEXPECTED_CELL_DRIFT",
  "UNEXPECTED_FORMULA_DRIFT",
  "UNEXPECTED_CACHE_DRIFT",
  "NEW_EXTERNAL_LINK",
  "UNEXPECTED_DEFINED_NAME_DRIFT",
  "UNEXPECTED_SHEET_STRUCTURE_DRIFT",
  "UNEXPECTED_VBA_DRIFT"
] as const;

export type ValidationErrorCode =
  (typeof VALIDATION_ERROR_CODES)[number];

export type PatchCellReference = {
  readonly sheet: string;
  readonly address: string;
};

export interface PatchReceiptContract {
  readonly changedCells: readonly PatchCellReference[];
  readonly changedParts: readonly string[];
  readonly affectedFormulaCells?: readonly PatchCellReference[];
  readonly formulaCells?: readonly PatchCellReference[];
  readonly schemaVersion?: "legacy-ooxml-patch-v1";
  readonly profileId?: "A" | "B" | "C";
  readonly sourceSha256?: string;
  readonly outputSha256?: string;
}

export type ValidationBuildInput = {
  readonly appVersion: string;
  readonly commitSha256: string;
  readonly signed: boolean;
};

export type OfficialSourceInput = {
  readonly sourceId: string;
  readonly effectiveFrom: string;
  readonly sha256: string;
};

export type ValidationReportRequest = {
  readonly originalBytes: Uint8Array;
  readonly outputBytes: Uint8Array;
  readonly manifestBytes: Uint8Array;
  readonly patchReceipt: PatchReceiptContract;
  readonly outputFilename: string;
  readonly generatedAtUtc: string;
  readonly build: ValidationBuildInput;
  readonly officialSources: readonly OfficialSourceInput[];
};

export type ValidationReportFailure = {
  readonly ok: false;
  readonly errors: readonly ValidationErrorCode[];
};
