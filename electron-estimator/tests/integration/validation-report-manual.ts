import {
  buildValidationReport,
  parseValidationReportBytes
} from "../../src/legacy/validation/index.js";
import {
  scenarioRequest,
  sha256
} from "./validation-report-fixtures.js";

const request = await scenarioRequest("A");
const result = await buildValidationReport(request);
if (!result.ok) {
  throw new TypeError(`Manual validation failed: ${result.errors.join(",")}`);
}
const parsed = parseValidationReportBytes(result.reportBytes);
if (
  parsed.schema_version !== "1.0" ||
  parsed.template.workbook_sha256 !== sha256(request.originalBytes) ||
  parsed.template.manifest_sha256 !== sha256(request.manifestBytes) ||
  parsed.output.workbook_sha256 !== sha256(request.outputBytes) ||
  parsed.output.formula_recalculated !== false ||
  parsed.changed_cells.length !== 0 ||
  parsed.official_sources.length !== 0 ||
  parsed.inherited_warnings.some(
    (warning) =>
      warning.output_count !== warning.baseline_count ||
      warning.delta !== 0
  ) ||
  result.reportSha256 !== sha256(result.reportBytes) ||
  result.reportBytes[0] === 0xef
) {
  throw new TypeError("Manual validation report observable mismatch");
}
process.stdout.write(
  new TextDecoder("utf-8", { fatal: true }).decode(result.reportBytes)
);
