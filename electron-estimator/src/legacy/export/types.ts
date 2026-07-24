import { isAbsolute } from "node:path";
import { z } from "zod";
import { PatchCellInputSchema } from "../patch/types.js";

const SHA256_PATTERN = /^[0-9a-f]{64}$/u;
const FINAL_NAME_PATTERN = /_검토초안_미재계산[.]xlsx$/u;

export const LEGACY_EXPORT_DISCLAIMER_VERSION =
  "legacy-export-disclaimer-v1" as const;

export const ATOMIC_EXPORT_STAGES = [
  "patch",
  "validation",
  "journal-prepare",
  "workbook-write",
  "workbook-sync",
  "workbook-close",
  "report-write",
  "report-sync",
  "report-close",
  "verify-workbook",
  "verify-report",
  "journal-staged",
  "journal-before-report",
  "rename-report",
  "journal-before-workbook",
  "rename-workbook",
  "journal-commit"
] as const;

export type AtomicExportStage = (typeof ATOMIC_EXPORT_STAGES)[number];

export const ATOMIC_EXPORT_ERROR_MESSAGES = {
  INVALID_EXPORT_REQUEST: "내보내기 요청 형식이 올바르지 않음.",
  EXPORT_DISCLAIMER_REQUIRED: "내부 검토용 내보내기 확인이 필요함.",
  SOURCE_DESTINATION_CONFLICT: "원본 파일과 같은 위치에는 저장할 수 없음.",
  DESTINATION_EXISTS: "같은 이름의 결과 파일이 이미 있음.",
  ATOMIC_EXPORT_ABORTED: "검증된 결과 파일 쌍을 만들지 못해 내보내기를 취소함."
} as const;

export type AtomicExportErrorCode =
  keyof typeof ATOMIC_EXPORT_ERROR_MESSAGES;

const BuildSchema = z.strictObject({
  appVersion: z.string().min(1),
  commitSha256: z.string().regex(SHA256_PATTERN),
  signed: z.boolean()
});

const OfficialSourceSchema = z.strictObject({
  sourceId: z.string().min(1),
  effectiveFrom: z.string().regex(/^\d{4}-\d{2}-\d{2}$/u),
  sha256: z.string().regex(SHA256_PATTERN)
});

const AbsolutePathSchema = z
  .string()
  .min(1)
  .refine(isSafeAbsolutePath);

export const AtomicLegacyExportRequestSchema = z
  .strictObject({
    sourcePath: AbsolutePathSchema,
    destinationPath: AbsolutePathSchema.regex(FINAL_NAME_PATTERN),
    expectedSourceSha256: z.string().regex(SHA256_PATTERN),
    itemCount: z.number().int().nonnegative(),
    cells: z.array(PatchCellInputSchema).readonly(),
    manifestBytes: z
      .custom<Uint8Array>((value) => value instanceof Uint8Array)
      .refine((bytes) => bytes.length > 0),
    generatedAtUtc: z
      .string()
      .datetime({ offset: true })
      .refine((value) => value.endsWith("Z")),
    build: BuildSchema,
    officialSources: z.array(OfficialSourceSchema).readonly(),
    disclaimer: z.strictObject({
      checked: z.boolean(),
      version: z.literal(LEGACY_EXPORT_DISCLAIMER_VERSION)
    })
  })
  .readonly();

export type AtomicLegacyExportRequest =
  z.output<typeof AtomicLegacyExportRequestSchema>;

export type AtomicCleanupReceipt = {
  readonly temporaryFilesCreated: number;
  readonly temporaryFilesRemoved: number;
  readonly finalFilesPublished: number;
  readonly finalFilesRolledBack: number;
  readonly complete: boolean;
};

export type AtomicLegacyExportSuccess = {
  readonly ok: true;
  readonly workbookName: string;
  readonly validationReportName: string;
  readonly sourceSha256: string;
  readonly workbookSha256: string;
  readonly validationReportSha256: string;
  readonly cleanup: AtomicCleanupReceipt;
};

export type AtomicLegacyExportFailure = {
  readonly ok: false;
  readonly error: {
    readonly code: AtomicExportErrorCode;
    readonly message: (typeof ATOMIC_EXPORT_ERROR_MESSAGES)[AtomicExportErrorCode];
  };
  readonly cleanup: AtomicCleanupReceipt;
};

export type AtomicLegacyExportResult =
  | AtomicLegacyExportSuccess
  | AtomicLegacyExportFailure;

export type AtomicExportOptions = {
  readonly timeoutMs?: number;
  readonly journalRoot?: string;
  readonly manifestRoot?: URL;
  readonly beforeStage?: (stage: AtomicExportStage) => Promise<void>;
};

export class AtomicExportError extends Error {
  readonly name = "AtomicExportError";

  constructor(readonly code: AtomicExportErrorCode) {
    super(ATOMIC_EXPORT_ERROR_MESSAGES[code]);
  }
}

function isSafeAbsolutePath(value: string): boolean {
  return isAbsolute(value) &&
    !value.split(/[\\/]+/u).includes("..");
}
