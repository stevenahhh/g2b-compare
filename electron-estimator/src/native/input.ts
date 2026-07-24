import { z } from "zod";
import { EstimateLineSchema, type EstimateLine } from "../domain/estimate.js";
import { OFFICIAL_DATA_REVISION } from "../domain/provenance.js";
import { SourcedProductObservationSchema } from "../official/schemas.js";
import { isValidNativeKoreaNetSelection } from "./selection-validation.js";

export const NATIVE_WORKBOOK_CAPACITY = 200;

const IdSchema = z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/u);
const NonemptySchema = z.string().trim().min(1);
const DateSchema = z.string().regex(/^\d{4}-\d{2}-\d{2}$/u);
const FieldSchema = z.enum(["CCTV", "LAN", "FIBER"]);

const SelectedResultSchema = z
  .strictObject({
    kind: z.literal("selected"),
    autoSelected: z.literal(true),
    reason: z.enum(["KOREANET_LOWEST", "KOREANET_TIED_LOWEST"]),
    selected: SourcedProductObservationSchema,
    lowestUnitPriceWon: z.number().int().positive(),
    comparableCandidates: z
      .array(SourcedProductObservationSchema)
      .min(2)
      .readonly()
  })
  .readonly();

const NotSelectedResultSchema = z
  .strictObject({
    kind: z.literal("not_selected"),
    autoSelected: z.literal(false),
    reason: z.enum([
      "KOREANET_NOT_AVAILABLE",
      "LOWER_AUTHENTIC_CANDIDATE",
      "NO_COMPARABLE_CANDIDATE",
      "SOURCE_EVIDENCE_INCOMPLETE",
      "SPECIFICATION_MISMATCH",
      "UNIT_MISMATCH"
    ]),
    selected: z.null(),
    lowestUnitPriceWon: z.number().int().positive().nullable(),
    comparableCandidates: z.array(SourcedProductObservationSchema).readonly()
  })
  .readonly();

const SelectionResultSchema = z.discriminatedUnion("kind", [
  SelectedResultSchema,
  NotSelectedResultSchema
]);

const NativeLineSchema = z
  .strictObject({
    field: FieldSchema,
    line: EstimateLineSchema
  })
  .readonly();

const NativeWorkbookInputSchema = z
  .strictObject({
    projectId: IdSchema,
    projectName: NonemptySchema,
    preparedOn: DateSchema,
    lines: z.array(NativeLineSchema).max(NATIVE_WORKBOOK_CAPACITY).readonly(),
    koreaNetSelections: z
      .array(
        z
          .strictObject({
            lineId: IdSchema,
            result: SelectionResultSchema
          })
          .readonly()
      )
      .default([])
      .readonly()
  })
  .readonly()
  .superRefine((input, context) => {
    const lineIds = new Set<string>();
    input.lines.forEach((entry, index) => {
      if (lineIds.has(entry.line.id)) {
        context.addIssue({
          code: "custom",
          message: "INVALID_INPUT",
          path: ["lines", index, "line", "id"]
        });
      }
      lineIds.add(entry.line.id);
      verifyLineProvenance(entry.line, index, context);
    });
    const selectedLineIds = new Set<string>();
    input.koreaNetSelections.forEach((selection, index) => {
      const line = input.lines.find(
        (entry) => entry.line.id === selection.lineId
      )?.line;
      if (
        !lineIds.has(selection.lineId) ||
        selectedLineIds.has(selection.lineId) ||
        !isValidNativeKoreaNetSelection(line, selection.result) ||
        (selection.result.kind === "selected" &&
          !matchesSelectedObservation(line, selection.result.selected))
      ) {
        context.addIssue({
          code: "custom",
          message: "KOREANET_SELECTION_CONFLICT",
          path: ["koreaNetSelections", index]
        });
      }
      selectedLineIds.add(selection.lineId);
    });
  });

export type NativeWorkbookInput = z.output<typeof NativeWorkbookInputSchema>;
export type NativeLine = NativeWorkbookInput["lines"][number];
export type NativeSelection = NativeWorkbookInput["koreaNetSelections"][number];

export type NativeWorkbookErrorCode =
  | "INVALID_INPUT"
  | "KOREANET_SELECTION_CONFLICT"
  | "NATIVE_CAPACITY_EXCEEDED"
  | "PRICING_METHOD_CONFLICT"
  | "STALE_PROVENANCE";

export class NativeWorkbookError extends Error {
  readonly name = "NativeWorkbookError";

  constructor(readonly code: NativeWorkbookErrorCode) {
    super(code);
  }
}

export function parseNativeWorkbookInput(input: unknown): NativeWorkbookInput {
  if (hasPricingConflict(input)) {
    throw new NativeWorkbookError("PRICING_METHOD_CONFLICT");
  }
  if (hasStaleRevision(input)) {
    throw new NativeWorkbookError("STALE_PROVENANCE");
  }
  const result = NativeWorkbookInputSchema.safeParse(input);
  if (result.success) {
    return result.data;
  }
  if (result.error.issues.some((issue) => issue.code === "too_big")) {
    throw new NativeWorkbookError("NATIVE_CAPACITY_EXCEEDED");
  }
  const explicit = result.error.issues.find(
    (issue) => issue.message === "KOREANET_SELECTION_CONFLICT"
  );
  throw new NativeWorkbookError(
    explicit === undefined ? "INVALID_INPUT" : "KOREANET_SELECTION_CONFLICT"
  );
}

export function excelSafeText(value: string): string {
  return /^\s*[=+\-@]/u.test(value) ? `'${value}` : value;
}

function verifyLineProvenance(
  line: EstimateLine,
  index: number,
  context: z.RefinementCtx
): void {
  const sources =
    line.cost.kind === "three_company_min"
      ? line.cost.quotes.map((quote) => quote.provenance)
      : [line.cost.provenance];
  if (
    sources.some(
      (source) =>
        "specification" in source &&
        (source.specification !== line.specification || source.unit !== line.unit)
    )
  ) {
    context.addIssue({
      code: "custom",
      message: "INVALID_INPUT",
      path: ["lines", index, "line", "cost"]
    });
  }
}

function matchesSelectedObservation(
  line: EstimateLine | undefined,
  selected: z.output<typeof SourcedProductObservationSchema>
): boolean {
  return (
    line?.cost.kind === "direct" &&
    line.cost.provenance.kind === "direct" &&
    selected.authenticity?.kind === "captured_source_payload" &&
    selected.authenticity.source_payload_sha256 ===
      selected.source_payload_sha256 &&
    selected.supplier_location_evidence !== undefined &&
    selected.service_area_evidence !== undefined &&
    selected.selection_evidence?.auto_selected === true &&
    line.cost.provenance.productId === selected.product_id &&
    line.cost.provenance.unitPriceWon.equals(selected.unit_price_won) &&
    line.cost.provenance.specification === selected.spec_snapshot &&
    line.cost.provenance.unit === selected.unit &&
    line.cost.provenance.sourcePayloadSha256 === selected.source_payload_sha256
  );
}

function hasPricingConflict(input: unknown): boolean {
  if (input === null || typeof input !== "object" || !("lines" in input)) {
    return false;
  }
  if (!Array.isArray(input.lines)) {
    return false;
  }
  return input.lines.some((entry) => {
    if (
      entry === null ||
      typeof entry !== "object" ||
      !("line" in entry) ||
      entry.line === null ||
      typeof entry.line !== "object" ||
      !("cost" in entry.line) ||
      entry.line.cost === null ||
      typeof entry.line.cost !== "object"
    ) {
      return false;
    }
    const cost = entry.line.cost;
    return (
      "marketPrice" in cost ||
      ("kind" in cost &&
        cost.kind === "market_price" &&
        ("productivity" in cost || "wages" in cost))
    );
  });
}

function hasStaleRevision(input: unknown): boolean {
  if (Array.isArray(input)) {
    return input.some(hasStaleRevision);
  }
  if (input === null || typeof input !== "object") {
    return false;
  }
  if (
    "datasetVersion" in input &&
    input.datasetVersion !== OFFICIAL_DATA_REVISION.datasetVersion
  ) {
    return true;
  }
  if (
    "compositeSha256" in input &&
    input.compositeSha256 !== OFFICIAL_DATA_REVISION.compositeSha256
  ) {
    return true;
  }
  if (
    "sourceManifestSha256" in input &&
    input.sourceManifestSha256 !== OFFICIAL_DATA_REVISION.sourceManifestSha256
  ) {
    return true;
  }
  return Object.values(input).some(hasStaleRevision);
}
