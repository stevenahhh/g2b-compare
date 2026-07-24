import { analyzeDrift, inspectPackagePair, manifestMatchesOriginal } from "./analysis.js";
import { canonicalJson, sha256 } from "./canonical.js";
import { parseManifest, parseRequestMetadata } from "./input.js";
import {
  ValidationReportSchema,
  type ValidationReport
} from "./schema.js";
import type {
  ValidationReportFailure,
  ValidationReportRequest
} from "./types.js";

export type ValidationReportSuccess = {
  readonly ok: true;
  readonly report: ValidationReport;
  readonly reportBytes: Uint8Array;
  readonly reportSha256: string;
};

export async function buildValidationReport(
  request: ValidationReportRequest
): Promise<ValidationReportSuccess | ValidationReportFailure> {
  let metadata: ReturnType<typeof parseRequestMetadata>;
  let manifest: ReturnType<typeof parseManifest>;
  try {
    metadata = parseRequestMetadata(request);
    manifest = parseManifest(request.manifestBytes);
  } catch (error) {
    if (error instanceof Error) {
      return { ok: false, errors: ["INVALID_REPORT_INPUT"] };
    }
    throw error;
  }
  const originalSha256 = sha256(request.originalBytes);
  if (originalSha256 !== manifest.source.sha256) {
    return { ok: false, errors: ["TEMPLATE_HASH_MISMATCH"] };
  }
  const outputSha256 = sha256(request.outputBytes);
  if (
    (metadata.patchReceipt.sourceSha256 !== undefined &&
      metadata.patchReceipt.sourceSha256 !== originalSha256) ||
    (metadata.patchReceipt.outputSha256 !== undefined &&
      metadata.patchReceipt.outputSha256 !== outputSha256) ||
    (metadata.patchReceipt.profileId !== undefined &&
      metadata.patchReceipt.profileId !== manifest.profileId)
  ) {
    return { ok: false, errors: ["PATCH_RECEIPT_MISMATCH"] };
  }
  let pair: Awaited<ReturnType<typeof inspectPackagePair>>;
  try {
    pair = await inspectPackagePair(
      request.originalBytes,
      request.outputBytes
    );
  } catch (error) {
    if (error instanceof Error) {
      return { ok: false, errors: ["MALFORMED_ZIP"] };
    }
    throw error;
  }
  if (!manifestMatchesOriginal(manifest, pair)) {
    return { ok: false, errors: ["STALE_MANIFEST"] };
  }
  let analysis: Awaited<ReturnType<typeof analyzeDrift>>;
  try {
    analysis = await analyzeDrift(manifest, request.patchReceipt, pair);
  } catch (error) {
    if (error instanceof Error) {
      return { ok: false, errors: ["MALFORMED_ZIP"] };
    }
    throw error;
  }
  if (analysis.errors.length > 0) {
    return { ok: false, errors: analysis.errors };
  }
  const report = ValidationReportSchema.parse({
    schema_version: "1.0",
    build: {
      app_version: metadata.build.appVersion,
      commit_sha256: metadata.build.commitSha256,
      signed: metadata.build.signed
    },
    scope: {
      profile_id: manifest.profileId,
      profile_slug: manifest.slug,
      generated_at_utc: metadata.generatedAtUtc,
      sheet_order: manifest.sheetMap.map(({ name }) => name)
    },
    template: {
      workbook_sha256: originalSha256,
      manifest_sha256: sha256(request.manifestBytes),
      baseline_sha256: sha256(canonicalJson(manifest.baselineInventory))
    },
    output: {
      filename: metadata.outputFilename,
      workbook_sha256: outputSha256,
      formula_recalculated: false
    },
    changed_cells: analysis.changedCells.map((cell) => ({
      sheet: cell.sheet,
      address: cell.address,
      before_sha256: cell.beforeSha256,
      output_sha256: cell.outputSha256
    })),
    inherited_warnings: [
      warning("cached_formula_error", analysis.warnings.cachedFormulaError),
      warning(
        "formula_reference_error",
        analysis.warnings.formulaReferenceError
      ),
      warning("external_link", analysis.warnings.externalLink),
      warning("problem_defined_name", analysis.warnings.problemDefinedName)
    ],
    official_sources: metadata.officialSources
      .toSorted((left, right) => left.sourceId.localeCompare(right.sourceId))
      .map((source) => ({
        source_id: source.sourceId,
        effective_from: source.effectiveFrom,
        sha256: source.sha256
    })),
    validation: {
      status: "pass",
      unexpected_parts: 0,
      unexpected_cells: 0,
      unexpected_formulas: 0,
      unexpected_caches: 0,
      new_external_links: 0,
      unexpected_defined_names: 0,
      unexpected_vba: 0
    }
  });
  const reportBytes = new TextEncoder().encode(JSON.stringify(report));
  return {
    ok: true,
    report,
    reportBytes,
    reportSha256: sha256(reportBytes)
  };
}

function warning(
  code:
    | "cached_formula_error"
    | "formula_reference_error"
    | "external_link"
    | "problem_defined_name",
  counts: readonly [number, number]
): {
  readonly code: typeof code;
  readonly baseline_count: number;
  readonly output_count: number;
  readonly delta: 0;
} {
  return {
    code,
    baseline_count: counts[0],
    output_count: counts[1],
    delta: 0
  };
}
