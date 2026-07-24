import { z } from "zod";

const NonemptySchema = z.string().trim().min(1);
const DateSchema = z.string().regex(/^\d{4}-\d{2}-\d{2}$/u);
const Sha256Schema = z.string().regex(/^[0-9a-f]{64}$/u);
const HttpsUrlSchema = z.string().url().startsWith("https://");
const PositiveIntegerSchema = z.number().int().positive();
const QualityFlagsSchema = z.array(NonemptySchema).readonly();
const SourcePagesSchema = z.array(PositiveIntegerSchema).nonempty().readonly();
const PositiveDecimalStringSchema = z
  .string()
  .regex(/^(?:0|[1-9]\d*)(?:\.\d+)?$/u)
  .refine((value) => Number(value) > 0);

const OfficialRowSourceShape = {
  effective_from: DateSchema,
  jurisdiction: z.literal("KR_NATIONWIDE"),
  license_id: NonemptySchema,
  quality_flags: QualityFlagsSchema,
  source_id: NonemptySchema,
  source_pdf_sha256: Sha256Schema,
  source_url: HttpsUrlSchema
};

export const MarketPriceRowSchema = z
  .strictObject({
    ...OfficialRowSourceShape,
    application_scope: NonemptySchema,
    category: z.enum(["CCTV", "LAN", "광케이블"]),
    kind: z.literal("market_price"),
    labor_ratio_bp: z.number().int().min(0).max(10_000),
    material_included: z.boolean(),
    name: NonemptySchema,
    source_pdf_page: PositiveIntegerSchema,
    specification: NonemptySchema,
    unit: NonemptySchema,
    unit_price_krw: PositiveIntegerSchema,
    work_code: NonemptySchema
  })
  .readonly();

export const ProductivityRowSchema = z
  .strictObject({
    ...OfficialRowSourceShape,
    category: z.enum(["CCTV", "LAN", "광케이블"]),
    coefficients_by_job_code: z
      .record(NonemptySchema, PositiveDecimalStringSchema)
      .refine((coefficients) => Object.keys(coefficients).length > 0)
      .readonly(),
    kind: z.literal("standard_productivity"),
    source_pdf_pages: SourcePagesSchema,
    specification: NonemptySchema,
    standard_item: NonemptySchema,
    standard_year: z.literal(2026),
    task: NonemptySchema,
    unit: NonemptySchema
  })
  .readonly();

export const WageRowSchema = z
  .strictObject({
    ...OfficialRowSourceShape,
    daily_wage_krw: PositiveIntegerSchema,
    job_code: NonemptySchema,
    job_name: NonemptySchema,
    kind: z.literal("wage_rate"),
    source_pdf_pages: SourcePagesSchema
  })
  .readonly();

const ManifestFileSchema = z
  .strictObject({
    dataset: z.enum(["market", "productivity", "wages"]),
    kind: z.enum(["market_price", "standard_productivity", "wage_rate"]),
    path: NonemptySchema,
    record_count: PositiveIntegerSchema,
    sha256: Sha256Schema,
    ordering: NonemptySchema,
    enriched_sha256: Sha256Schema
  })
  .readonly();

const ManifestSourceSchema = z
  .looseObject({
    source_id: NonemptySchema,
    url: HttpsUrlSchema,
    pdf_sha256: Sha256Schema,
    effective_from: DateSchema,
    bundled: z.literal(false),
    license: z.looseObject({ identifier: NonemptySchema }).readonly()
  })
  .readonly();

export const OfficialSourceManifestSchema = z
  .looseObject({
    schema_version: z.literal("official-source-manifest-v1"),
    dataset_version: NonemptySchema,
    files: z.array(ManifestFileSchema).length(3).readonly(),
    composite_sha256: Sha256Schema,
    market_breakdown: z
      .strictObject({
        categories: z
          .strictObject({
            CCTV: PositiveIntegerSchema,
            LAN: PositiveIntegerSchema,
            FIBER: PositiveIntegerSchema
          })
          .readonly(),
        material_included: PositiveIntegerSchema,
        material_excluded: PositiveIntegerSchema,
        reason_by_state: z
          .strictObject({
            included: NonemptySchema,
            excluded: NonemptySchema
          })
          .readonly()
      })
      .readonly(),
    sources: z.array(ManifestSourceSchema).length(3).readonly(),
    source_manifest_sha256: Sha256Schema
  })
  .readonly();

const AuthenticitySchema = z
  .strictObject({
    kind: z.literal("captured_source_payload"),
    source_payload_sha256: Sha256Schema
  })
  .readonly();

const ProvenanceEvidenceSchema = z
  .strictObject({
    statement: NonemptySchema,
    source_url: HttpsUrlSchema,
    observed_at: z.string().datetime({ offset: true }),
    source_payload_sha256: Sha256Schema
  })
  .readonly();

const SelectionEvidenceSchema = z
  .strictObject({
    comparison_group: NonemptySchema,
    specification_fingerprint: Sha256Schema,
    eligible: z.boolean(),
    auto_selected: z.boolean(),
    lowest_observed_unit_price_won: PositiveIntegerSchema,
    compared_observation_ids: z.array(NonemptySchema).min(2).readonly()
  })
  .readonly();

export const SourcedProductObservationSchema = z
  .strictObject({
    observation_id: NonemptySchema,
    product_id: z.string().regex(/^\d{8}$/u),
    supplier_name: NonemptySchema,
    unit_price_won: PositiveIntegerSchema,
    unit: NonemptySchema,
    spec_snapshot: NonemptySchema,
    source_url: HttpsUrlSchema,
    api_operation: NonemptySchema,
    observed_at: z.string().datetime({ offset: true }),
    source_payload_sha256: Sha256Schema,
    authenticity: AuthenticitySchema.optional(),
    supplier_location_evidence: ProvenanceEvidenceSchema.optional(),
    service_area_evidence: ProvenanceEvidenceSchema.optional(),
    selection_evidence: SelectionEvidenceSchema.optional(),
    synthetic: z.boolean().optional()
  })
  .readonly();

export const SourcedProductsManifestSchema = z
  .strictObject({
    schema_version: z.literal("sourced-product-observation-manifest-v1"),
    ledger_kind: z.literal("authentic_production"),
    canonical_format: z.literal("canonical_json_array_lf"),
    observation_file: z.literal("observations.json"),
    schema_file: z.literal("sourced-product-observation.schema.json"),
    record_count: z.number().int().nonnegative(),
    canonical_sha256: Sha256Schema,
    fabricated_rows: z.literal(0),
    source_data_risk: NonemptySchema
  })
  .readonly();

export type MarketPriceRow = z.output<typeof MarketPriceRowSchema>;
export type ProductivityRow = z.output<typeof ProductivityRowSchema>;
export type WageRow = z.output<typeof WageRowSchema>;
export type OfficialSourceManifest = z.output<
  typeof OfficialSourceManifestSchema
>;
export type SourcedProductObservation = z.output<
  typeof SourcedProductObservationSchema
>;
