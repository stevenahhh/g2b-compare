import { z } from "zod";
import {
  EstimateInputSchema,
  OFFICIAL_DATA_REVISION
} from "../shared/contracts.js";
import {
  LegacyExportRequestSchema,
  LegacyImportSessionSchema,
  LegacyWorkflowFailureSchema
} from "../workflows/legacy/contracts.js";
import {
  NativeCatalogSchema,
  NativeProjectWireSchema,
  NativeSelectionRequestSchema,
  NativeSelectionResultSchema
} from "../workflows/native/contracts.js";

export const IPC_CHANNELS = {
  dialog: "estimator:dialog",
  import: "estimator:import",
  export: "estimator:export",
  readSeed: "estimator:readSeed",
  getBuildInfo: "estimator:getBuildInfo"
} as const;

export const BRIDGE_ERROR_CODES = [
  "IPC_SENDER_REJECTED",
  "IPC_PAYLOAD_REJECTED",
  "IPC_CAPABILITY_REJECTED",
  "IPC_RESPONSE_REJECTED",
  "IPC_OPERATION_UNAVAILABLE",
  "IPC_INTERNAL_ERROR"
] as const;

export type BridgeErrorCode = (typeof BRIDGE_ERROR_CODES)[number];

export const BRIDGE_ERROR_MESSAGES = {
  IPC_SENDER_REJECTED: "요청 출처를 확인할 수 없음.",
  IPC_PAYLOAD_REJECTED: "요청 형식이 올바르지 않음.",
  IPC_CAPABILITY_REJECTED: "파일 권한이 만료되었거나 유효하지 않음.",
  IPC_RESPONSE_REJECTED: "응답 형식이 올바르지 않음.",
  IPC_OPERATION_UNAVAILABLE: "아직 사용할 수 없는 기능임.",
  IPC_INTERNAL_ERROR: "요청을 처리하지 못했음."
} as const satisfies Record<BridgeErrorCode, string>;

const BridgeErrorSchema = z
  .strictObject({
    code: z.enum(BRIDGE_ERROR_CODES),
    message: z.enum([
      BRIDGE_ERROR_MESSAGES.IPC_SENDER_REJECTED,
      BRIDGE_ERROR_MESSAGES.IPC_PAYLOAD_REJECTED,
      BRIDGE_ERROR_MESSAGES.IPC_CAPABILITY_REJECTED,
      BRIDGE_ERROR_MESSAGES.IPC_RESPONSE_REJECTED,
      BRIDGE_ERROR_MESSAGES.IPC_OPERATION_UNAVAILABLE,
      BRIDGE_ERROR_MESSAGES.IPC_INTERNAL_ERROR
    ])
  })
  .readonly();

const CapabilityIdSchema = z.string().uuid();
const SafeFileNameSchema = z
  .string()
  .trim()
  .min(1)
  .max(255)
  .refine((name) => !/[\\/]/u.test(name));
const EmptyRequestSchema = z.strictObject({}).readonly();

const DialogResultSchema = z.discriminatedUnion("cancelled", [
  z.strictObject({ cancelled: z.literal(true) }).readonly(),
  z
    .strictObject({
      cancelled: z.literal(false),
      capabilityId: CapabilityIdSchema,
      name: SafeFileNameSchema
    })
    .readonly()
]);

const LegacyExportResultSchema = z
  .strictObject({
    workbookName: SafeFileNameSchema,
    validationReportName: SafeFileNameSchema
  })
  .readonly();
const NativeExportResultSchema = z
  .strictObject({
    workbookName: SafeFileNameSchema,
    sheetCount: z.literal(6)
  })
  .readonly();
const ExportResultSchema = z.union([
  LegacyExportResultSchema,
  LegacyWorkflowFailureSchema,
  NativeExportResultSchema
]);

export const MainBuildInfoSchema = z
  .strictObject({
    appVersion: z.string().min(1),
    electronVersion: z.string().min(1),
    chromeVersion: z.string().min(1),
    unsigned: z.literal(true)
  })
  .readonly();

export const RuntimeBuildInfoSchema = z
  .strictObject({
    appVersion: z.string().min(1),
    electronVersion: z.string().min(1),
    chromeVersion: z.string().min(1),
    unsigned: z.literal(true),
    sandboxed: z.literal(true),
    contextIsolated: z.literal(true)
  })
  .readonly();

const SeedInfoSchema = z
  .strictObject({
    datasetVersion: z.literal(OFFICIAL_DATA_REVISION.datasetVersion),
    compositeSha256: z.literal(OFFICIAL_DATA_REVISION.compositeSha256),
    sourceManifestSha256: z.literal(
      OFFICIAL_DATA_REVISION.sourceManifestSha256
    )
  })
  .readonly();

function responseSchema<T extends z.ZodType>(value: T) {
  return z.union([
    z.strictObject({ ok: z.literal(true), value }).readonly(),
    z.strictObject({ ok: z.literal(false), error: BridgeErrorSchema }).readonly()
  ]);
}

export const DialogRequestSchema = z
  .strictObject({ kind: z.enum(["import", "export", "legacy_export"]) })
  .readonly();
export const DialogResponseSchema = responseSchema(DialogResultSchema);
export const ImportRequestSchema = z
  .strictObject({ capabilityId: CapabilityIdSchema })
  .readonly();
export const ImportResponseSchema = responseSchema(
  z.union([EstimateInputSchema, LegacyImportSessionSchema])
);
export const ExportRequestSchema = z.union([
  z
    .strictObject({
      capabilityId: CapabilityIdSchema,
      estimate: EstimateInputSchema
    })
    .readonly(),
  z
    .strictObject({
      kind: z.literal("native_workbook"),
      capabilityId: CapabilityIdSchema,
      project: NativeProjectWireSchema
    })
    .readonly(),
  LegacyExportRequestSchema
]);
export const ExportResponseSchema = responseSchema(ExportResultSchema);
export const ReadSeedRequestSchema = z.union([
  EmptyRequestSchema,
  z.strictObject({ kind: z.literal("native_catalog") }).readonly(),
  z
    .strictObject({
      kind: z.literal("native_select"),
      requestedItemKey:
        NativeSelectionRequestSchema.unwrap().shape.requestedItemKey,
      specification:
        NativeSelectionRequestSchema.unwrap().shape.specification,
      unit: NativeSelectionRequestSchema.unwrap().shape.unit
    })
    .readonly()
]);
export const ReadSeedResponseSchema = responseSchema(
  z.union([SeedInfoSchema, NativeCatalogSchema, NativeSelectionResultSchema])
);
export const BuildInfoRequestSchema = EmptyRequestSchema;
export const MainBuildInfoResponseSchema = responseSchema(MainBuildInfoSchema);
export const RuntimeBuildInfoResponseSchema = responseSchema(
  RuntimeBuildInfoSchema
);

export type DialogRequest = z.output<typeof DialogRequestSchema>;
export type ImportRequest = z.output<typeof ImportRequestSchema>;
export type ExportRequest = z.output<typeof ExportRequestSchema>;
export type ReadSeedRequest = z.output<typeof ReadSeedRequestSchema>;

export function bridgeError(code: BridgeErrorCode): {
  readonly ok: false;
  readonly error: {
    readonly code: BridgeErrorCode;
    readonly message: (typeof BRIDGE_ERROR_MESSAGES)[BridgeErrorCode];
  };
} {
  return {
    ok: false,
    error: {
      code,
      message: BRIDGE_ERROR_MESSAGES[code]
    }
  };
}
