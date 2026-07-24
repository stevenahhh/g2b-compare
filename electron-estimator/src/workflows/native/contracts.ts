import { z } from "zod";
import { OFFICIAL_DATA_REVISION } from "../../domain/provenance.js";
import {
  MarketPriceRowSchema,
  ProductivityRowSchema,
  SourcedProductObservationSchema,
  WageRowSchema
} from "../../official/schemas.js";

const RevisionSchema = z
  .strictObject({
    datasetVersion: z.literal(OFFICIAL_DATA_REVISION.datasetVersion),
    compositeSha256: z.literal(OFFICIAL_DATA_REVISION.compositeSha256),
    sourceManifestSha256: z.literal(
      OFFICIAL_DATA_REVISION.sourceManifestSha256
    )
  })
  .readonly();

export const NativeCatalogSchema = z
  .strictObject({
    revision: RevisionSchema,
    marketPrices: z.array(MarketPriceRowSchema).readonly(),
    productivity: z.array(ProductivityRowSchema).readonly(),
    wages: z.array(WageRowSchema).readonly(),
    sourcedProducts: z.array(SourcedProductObservationSchema).readonly()
  })
  .readonly();

const SelectionReasonSchema = z.enum([
  "KOREANET_LOWEST",
  "KOREANET_NOT_AVAILABLE",
  "KOREANET_TIED_LOWEST",
  "LOWER_AUTHENTIC_CANDIDATE",
  "NO_COMPARABLE_CANDIDATE",
  "SOURCE_EVIDENCE_INCOMPLETE",
  "SPECIFICATION_MISMATCH",
  "UNIT_MISMATCH"
]);

export const NativeSelectionRequestSchema = z
  .strictObject({
    requestedItemKey: z.string().trim().min(1),
    specification: z.string().trim().min(1),
    unit: z.string().trim().min(1)
  })
  .readonly();

export const NativeSelectionResultSchema = z.discriminatedUnion("kind", [
  z
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
    .readonly(),
  z
    .strictObject({
      kind: z.literal("not_selected"),
      autoSelected: z.literal(false),
      reason: SelectionReasonSchema.exclude([
        "KOREANET_LOWEST",
        "KOREANET_TIED_LOWEST"
      ]),
      selected: z.null(),
      lowestUnitPriceWon: z.number().int().positive().nullable(),
      comparableCandidates: z.array(SourcedProductObservationSchema).readonly()
    })
    .readonly()
]);

const NativeSelectionSchema = z
  .strictObject({
    lineId: z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/u),
    result: NativeSelectionResultSchema
  })
  .readonly();

export const NativeProjectWireSchema = z
  .strictObject({
    projectId: z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/u),
    projectName: z.string().trim().min(1),
    preparedOn: z.string().regex(/^\d{4}-\d{2}-\d{2}$/u),
    lines: z
      .array(
        z
          .strictObject({
            field: z.enum(["CCTV", "LAN", "FIBER"]),
            line: z.unknown()
          })
          .readonly()
      )
      .max(200)
      .readonly(),
    koreaNetSelections: z.array(NativeSelectionSchema).readonly()
  })
  .readonly();

export type NativeCatalog = z.output<typeof NativeCatalogSchema>;
export type NativeSelectionRequest = z.output<
  typeof NativeSelectionRequestSchema
>;
export type NativeSelectionResult = z.output<typeof NativeSelectionResultSchema>;
export type NativeProjectWire = z.output<typeof NativeProjectWireSchema>;
