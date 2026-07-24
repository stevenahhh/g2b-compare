import { z } from "zod";

const Sha256Schema = z.string().regex(/^[0-9a-f]{64}$/u);
const DateSchema = z.string().regex(/^\d{4}-\d{2}-\d{2}$/u);
const UtcTimestampSchema = z
  .string()
  .datetime({ offset: true })
  .refine((value) => value.endsWith("Z"));
const CellAddressSchema = z.string().regex(/^[A-Z]+\d+$/u);
const WarningCodeSchema = z.enum([
  "cached_formula_error",
  "formula_reference_error",
  "external_link",
  "problem_defined_name"
]);
const BuildSchema = z.strictObject({
  app_version: z.string().min(1),
  commit_sha256: Sha256Schema,
  signed: z.boolean()
});
const ScopeSchema = z.strictObject({
  profile_id: z.enum(["A", "B", "C"]),
  profile_slug: z.string().min(1),
  generated_at_utc: UtcTimestampSchema,
  sheet_order: z.array(z.string().min(1)).min(1).readonly()
});
const TemplateSchema = z.strictObject({
  workbook_sha256: Sha256Schema,
  manifest_sha256: Sha256Schema,
  baseline_sha256: Sha256Schema
});
const OutputSchema = z.strictObject({
  filename: z.string().endsWith("_검토초안_미재계산.xlsx"),
  workbook_sha256: Sha256Schema,
  formula_recalculated: z.literal(false)
});
const ChangedCellSchema = z.strictObject({
  sheet: z.string().min(1),
  address: CellAddressSchema,
  before_sha256: Sha256Schema,
  output_sha256: Sha256Schema
});
const WarningSchema = z.strictObject({
  code: WarningCodeSchema,
  baseline_count: z.number().int().nonnegative(),
  output_count: z.number().int().nonnegative(),
  delta: z.literal(0)
});
const OfficialSourceSchema = z.strictObject({
  source_id: z.string().min(1),
  effective_from: DateSchema,
  sha256: Sha256Schema
});
const ValidationSchema = z.strictObject({
  status: z.literal("pass"),
  unexpected_parts: z.literal(0),
  unexpected_cells: z.literal(0),
  unexpected_formulas: z.literal(0),
  unexpected_caches: z.literal(0),
  new_external_links: z.literal(0),
  unexpected_defined_names: z.literal(0),
  unexpected_vba: z.literal(0)
});
const WARNING_ORDER = [
  "cached_formula_error",
  "formula_reference_error",
  "external_link",
  "problem_defined_name"
] as const;

export const ValidationReportSchema = z
  .strictObject({
    schema_version: z.literal("1.0"),
    build: BuildSchema,
    scope: ScopeSchema,
    template: TemplateSchema,
    output: OutputSchema,
    changed_cells: z.array(ChangedCellSchema).readonly(),
    inherited_warnings: z.array(WarningSchema).length(4).readonly(),
    official_sources: z.array(OfficialSourceSchema).readonly(),
    validation: ValidationSchema
  })
  .superRefine((report, context) => {
    for (const [index, code] of WARNING_ORDER.entries()) {
      const warning = report.inherited_warnings[index];
      if (
        warning?.code !== code ||
        warning.output_count !== warning.baseline_count
      ) {
        context.addIssue({
          code: "custom",
          message: "INVALID_WARNING_BASELINE",
          path: ["inherited_warnings", index]
        });
      }
    }
    if (!isSortedSources(report.official_sources)) {
      context.addIssue({
        code: "custom",
        message: "UNSORTED_OFFICIAL_SOURCES",
        path: ["official_sources"]
      });
    }
    if (!isSortedCells(report.changed_cells, report.scope.sheet_order)) {
      context.addIssue({
        code: "custom",
        message: "UNSORTED_CHANGED_CELLS",
        path: ["changed_cells"]
      });
    }
  });

export type ValidationReport = z.output<typeof ValidationReportSchema>;

export function parseValidationReportBytes(
  bytes: Uint8Array
): ValidationReport {
  if (
    bytes[0] === 0xef &&
    bytes[1] === 0xbb &&
    bytes[2] === 0xbf
  ) {
    throw new TypeError("INVALID_VALIDATION_REPORT");
  }
  let input: unknown;
  try {
    const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    input = JSON.parse(text);
  } catch (error) {
    if (error instanceof Error) {
      throw new TypeError("INVALID_VALIDATION_REPORT", { cause: error });
    }
    throw error;
  }
  return ValidationReportSchema.parse(input);
}

function isSortedSources(
  sources: readonly { readonly source_id: string }[]
): boolean {
  return sources.every(
    (source, index) =>
      index === 0 ||
      (sources[index - 1]?.source_id.localeCompare(source.source_id) ?? 0) <= 0
  );
}

function isSortedCells(
  cells: readonly { readonly sheet: string; readonly address: string }[],
  sheetOrder: readonly string[]
): boolean {
  return cells.every((cell, index) => {
    const previous = cells[index - 1];
    return previous === undefined ||
      compareCellReference(previous, cell, sheetOrder) <= 0;
  });
}

function compareCellReference(
  left: { readonly sheet: string; readonly address: string },
  right: { readonly sheet: string; readonly address: string },
  sheetOrder: readonly string[]
): number {
  return (
    sheetOrder.indexOf(left.sheet) - sheetOrder.indexOf(right.sheet) ||
    row(left.address) - row(right.address) ||
    column(left.address) - column(right.address)
  );
}

function row(address: string): number {
  return Number(address.match(/\d+$/u)?.[0] ?? 0);
}

function column(address: string): number {
  return [...(address.match(/^[A-Z]+/u)?.[0] ?? "")].reduce(
    (value, character) => value * 26 + character.charCodeAt(0) - 64,
    0
  );
}
