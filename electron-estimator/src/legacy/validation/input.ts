import { z } from "zod";
import {
  LegacyProfileManifestSchema,
  type LegacyProfileManifest
} from "../inspect/profile.js";
import type { ValidationReportRequest } from "./types.js";

const Sha256Schema = z.string().regex(/^[0-9a-f]{64}$/u);
const CellReferenceSchema = z.object({
  sheet: z.string().min(1),
  address: z.string().regex(/^[A-Z]+\d+$/u)
});
const ReceiptSchema = z
  .strictObject({
    changedCells: z.array(CellReferenceSchema).readonly(),
    changedParts: z.array(z.string().min(1)).readonly(),
    affectedFormulaCells: z.array(CellReferenceSchema).readonly().optional(),
    formulaCells: z.array(CellReferenceSchema).readonly().optional(),
    schemaVersion: z.literal("legacy-ooxml-patch-v1").optional(),
    profileId: z.enum(["A", "B", "C"]).optional(),
    sourceSha256: Sha256Schema.optional(),
    outputSha256: Sha256Schema.optional()
  })
  .superRefine((receipt, context) => {
    const groups = [
      receipt.changedCells.map(referenceKey),
      receipt.changedParts,
      (receipt.affectedFormulaCells ?? []).map(referenceKey),
      (receipt.formulaCells ?? []).map(referenceKey)
    ];
    if (groups.some((group) => new Set(group).size !== group.length)) {
      context.addIssue({ code: "custom", message: "DUPLICATE_RECEIPT_ENTRY" });
    }
  });
const MetadataSchema = z.strictObject({
  patchReceipt: ReceiptSchema,
  outputFilename: z.string().endsWith("_검토초안_미재계산.xlsx"),
  generatedAtUtc: z
    .string()
    .datetime({ offset: true })
    .refine((value) => value.endsWith("Z")),
  build: z.strictObject({
    appVersion: z.string().min(1),
    commitSha256: Sha256Schema,
    signed: z.boolean()
  }),
  officialSources: z
    .array(
      z.strictObject({
        sourceId: z.string().min(1),
        effectiveFrom: z.string().regex(/^\d{4}-\d{2}-\d{2}$/u),
        sha256: Sha256Schema
      })
    )
    .readonly()
});
export type ValidationRequestMetadata = z.output<typeof MetadataSchema>;

export function parseRequestMetadata(
  request: ValidationReportRequest
): ValidationRequestMetadata {
  if (
    !(request.originalBytes instanceof Uint8Array) ||
    !(request.outputBytes instanceof Uint8Array) ||
    !(request.manifestBytes instanceof Uint8Array) ||
    request.originalBytes.byteLength === 0 ||
    request.outputBytes.byteLength === 0 ||
    request.manifestBytes.byteLength === 0
  ) {
    throw new TypeError("INVALID_REPORT_INPUT");
  }
  return MetadataSchema.parse({
    patchReceipt: request.patchReceipt,
    outputFilename: request.outputFilename,
    generatedAtUtc: request.generatedAtUtc,
    build: request.build,
    officialSources: request.officialSources
  });
}

export function parseManifest(bytes: Uint8Array): LegacyProfileManifest {
  let input: unknown;
  try {
    input = JSON.parse(
      new TextDecoder("utf-8", { fatal: true }).decode(bytes)
    );
  } catch (error) {
    if (error instanceof Error) {
      throw new TypeError("STALE_MANIFEST", { cause: error });
    }
    throw error;
  }
  return LegacyProfileManifestSchema.parse(input);
}

function referenceKey(reference: {
  readonly sheet: string;
  readonly address: string;
}): string {
  return `${reference.sheet}!${reference.address}`;
}
