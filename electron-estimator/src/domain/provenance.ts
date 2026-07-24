import { z } from "zod";
import { PositiveDecimalSchema, PositiveWonSchema } from "./money.js";

const SHA256Schema = z.string().regex(/^[0-9a-f]{64}$/u, {
  message: "INVALID_PROVENANCE"
});
const DateSchema = z.string().regex(/^\d{4}-\d{2}-\d{2}$/u, {
  message: "INVALID_PROVENANCE"
});
const TimestampSchema = z.string().datetime({ offset: true });
const HttpsUrlSchema = z.string().url().startsWith("https://");
const NonemptySchema = z.string().trim().min(1);

export const OFFICIAL_DATA_REVISION = {
  datasetVersion: "2026-H2-KR-CCTV-LAN-FIBER-v1",
  compositeSha256: "0705bbc698818fd1b291df2c554028253777e10503863fe2564830faf7e3fe16",
  sourceManifestSha256: "482309efcfd22ca0cc15dc55c3e08d9b1dc01ae6ef15187946ccdf53fc0f0745"
} as const;

const DatasetVersionSchema = z.literal(OFFICIAL_DATA_REVISION.datasetVersion, {
  error: "STALE_PROVENANCE"
});
const CompositeSha256Schema = z.literal(OFFICIAL_DATA_REVISION.compositeSha256, {
  error: "STALE_PROVENANCE"
});
const SourceManifestSha256Schema = z.literal(
  OFFICIAL_DATA_REVISION.sourceManifestSha256,
  { error: "STALE_PROVENANCE" }
);

const OfficialReferenceShape = {
  datasetVersion: DatasetVersionSchema,
  compositeSha256: CompositeSha256Schema,
  sourceManifestSha256: SourceManifestSha256Schema,
  sourceId: NonemptySchema,
  sourceUrl: HttpsUrlSchema,
  sourcePdfSha256: SHA256Schema,
  sourcePdfPages: z.array(z.number().int().positive()).nonempty().readonly(),
  effectiveFrom: DateSchema,
  jurisdiction: NonemptySchema
};

const OfficialReferenceSchema = z.strictObject(OfficialReferenceShape).readonly();

export const DirectProvenanceSchema = z
  .strictObject({
    kind: z.literal("direct"),
    observationId: NonemptySchema,
    productId: z.string().regex(/^\d{8}$/u, { message: "INVALID_ID" }),
    supplierName: NonemptySchema,
    unitPriceWon: PositiveWonSchema,
    specification: NonemptySchema,
    unit: NonemptySchema,
    sourceUrl: HttpsUrlSchema,
    apiOperation: NonemptySchema,
    observedAt: TimestampSchema,
    sourcePayloadSha256: SHA256Schema
  })
  .readonly();

export const UserQuoteProvenanceSchema = z
  .strictObject({
    kind: z.literal("user_quote"),
    quoteId: NonemptySchema,
    supplierName: NonemptySchema,
    unitPriceWon: PositiveWonSchema,
    specification: NonemptySchema,
    unit: NonemptySchema,
    quoteDate: DateSchema,
    documentSha256: SHA256Schema
  })
  .readonly();

export const QuoteSourceSchema = z.discriminatedUnion("kind", [
  DirectProvenanceSchema,
  UserQuoteProvenanceSchema
]);

export type QuoteSource = z.output<typeof QuoteSourceSchema>;

export const MarketPriceProvenanceSchema = z
  .strictObject({
    kind: z.literal("market_price"),
    ...OfficialReferenceShape,
    workCode: NonemptySchema,
    specification: NonemptySchema,
    unit: NonemptySchema,
    materialIncluded: z.boolean(),
    unitPriceWon: PositiveWonSchema
  })
  .readonly();

const ProductivityCoefficientSchema = z
  .strictObject({
    jobCode: NonemptySchema,
    coefficient: PositiveDecimalSchema,
    dailyWageWon: PositiveWonSchema,
    wageSource: OfficialReferenceSchema
  })
  .readonly();

export const StandardQuantityProvenanceSchema = z
  .strictObject({
    kind: z.literal("standard_quantity"),
    ...OfficialReferenceShape,
    standardItem: NonemptySchema,
    task: NonemptySchema,
    specification: NonemptySchema,
    unit: NonemptySchema,
    coefficients: z.array(ProductivityCoefficientSchema).nonempty().readonly()
  })
  .readonly();

export const RateContextSchema = z
  .strictObject({
    issuer: NonemptySchema,
    regime: z.enum(["national", "local"]),
    noticeOrContractDate: DateSchema,
    projectType: NonemptySchema,
    contractLevel: z.enum(["general", "subcontract"]),
    amountBasis: NonemptySchema,
    suppliedMaterials: z.enum(["included", "excluded", "mixed"]),
    pricingMethod: NonemptySchema,
    vatStatus: z.enum(["included", "excluded", "unknown"]),
    datasetVersion: DatasetVersionSchema,
    compositeSha256: CompositeSha256Schema,
    sourceManifestSha256: SourceManifestSha256Schema
  })
  .readonly();

const SelectionCandidateASchema = selectionCandidate("A");
const SelectionCandidateBSchema = selectionCandidate("B");
const SelectionCandidateCSchema = selectionCandidate("C");

export const ThreeCompanyMinimumProvenanceSchema = z
  .strictObject({
    kind: z.literal("three_company_min"),
    selectedSlot: z.enum(["A", "B", "C"]),
    selectedQuoteId: NonemptySchema,
    candidates: z
      .tuple([
        SelectionCandidateASchema,
        SelectionCandidateBSchema,
        SelectionCandidateCSchema
      ])
      .readonly()
  })
  .readonly();

export type DirectProvenance = z.output<typeof DirectProvenanceSchema>;
export type MarketPriceProvenance = z.output<typeof MarketPriceProvenanceSchema>;
export type StandardQuantityProvenance = z.output<
  typeof StandardQuantityProvenanceSchema
>;
export type ThreeCompanyMinimumProvenance = z.output<
  typeof ThreeCompanyMinimumProvenanceSchema
>;
export type RateContext = z.output<typeof RateContextSchema>;
export type Provenance =
  | QuoteSource
  | MarketPriceProvenance
  | StandardQuantityProvenance
  | ThreeCompanyMinimumProvenance;

export function quoteSourceIdentity(source: QuoteSource): {
  readonly quoteId: string;
  readonly unitPriceWon: QuoteSource["unitPriceWon"];
} {
  switch (source.kind) {
    case "direct":
      return { quoteId: source.observationId, unitPriceWon: source.unitPriceWon };
    case "user_quote":
      return { quoteId: source.quoteId, unitPriceWon: source.unitPriceWon };
    default:
      return assertNever(source);
  }
}

export function serializeProvenance(provenance: Provenance): string {
  return JSON.stringify(provenance);
}

function selectionCandidate(slot: "A" | "B" | "C") {
  return z
    .strictObject({
      slot: z.literal(slot),
      quoteId: NonemptySchema,
      unitPriceWon: PositiveWonSchema
    })
    .readonly();
}

function assertNever(value: never): never {
  throw new TypeError(`Unexpected provenance: ${String(value)}`);
}
