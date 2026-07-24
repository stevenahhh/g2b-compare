import { createHash } from "node:crypto";
import { basename } from "node:path";
import type { PatchedLegacyWorkbook } from "../patch/index.js";
import {
  parseValidationReportBytes,
  type ValidationReportSuccess
} from "../validation/index.js";
import {
  runStage,
  verifyTemporary
} from "./files.js";
import type { ExportPaths } from "./paths.js";
import {
  AtomicExportError,
  type AtomicExportOptions
} from "./types.js";

export async function verifyTemporaryPair(input: {
  readonly paths: ExportPaths;
  readonly patched: PatchedLegacyWorkbook;
  readonly validation: ValidationReportSuccess;
  readonly options: AtomicExportOptions;
  readonly signal: AbortSignal;
}): Promise<{
  readonly workbookSha256: string;
  readonly validationReportSha256: string;
}> {
  await runStage("verify-workbook", input.options, input.signal);
  const workbookBytes = await verifyTemporary(
    input.paths.workbookTemporary,
    input.patched.workbook,
    input.signal
  );
  await runStage("verify-report", input.options, input.signal);
  const reportBytes = await verifyTemporary(
    input.paths.reportTemporary,
    input.validation.reportBytes,
    input.signal
  );
  const report = parseValidationReportBytes(reportBytes);
  const workbookSha256 = sha256(workbookBytes);
  const validationReportSha256 = sha256(reportBytes);
  if (
    report.output.filename !== basename(input.paths.workbook) ||
    report.output.workbook_sha256 !== workbookSha256 ||
    report.output.formula_recalculated !== false ||
    report.validation.status !== "pass" ||
    validationReportSha256 !== input.validation.reportSha256
  ) {
    throw new AtomicExportError("ATOMIC_EXPORT_ABORTED");
  }
  return { workbookSha256, validationReportSha256 };
}

function sha256(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex");
}
