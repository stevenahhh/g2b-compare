import { readFile, readdir } from "node:fs/promises";
import { join } from "node:path";
import { exportLegacyWorkbook } from "../../src/legacy/export/index.js";
import { parseValidationReportBytes } from "../../src/legacy/validation/index.js";
import {
  exportFixture,
  exportOptions,
  fileSha256,
  journalEntries,
  removeTemporaryDirectory,
  sha256,
  temporaryExportDirectory
} from "./atomic-export-fixtures.js";

const receipt = await (async () => {
  const directory = await temporaryExportDirectory();
  try {
    const request = await exportFixture("A", directory, "manual-A");
    const sourceHashBefore = await fileSha256(request.sourcePath);
    const result = await exportLegacyWorkbook(
      request,
      exportOptions(directory)
    );
    if (!result.ok) {
      throw new TypeError(result.error.code);
    }
    const files = await readdir(directory);
    const workbookBytes = await readFile(
      join(directory, result.workbookName)
    );
    const reportBytes = await readFile(
      join(directory, result.validationReportName)
    );
    const report = parseValidationReportBytes(reportBytes);
    return {
      scenario: "exact-profile-A",
      finalFiles: files.toSorted(),
      workbookSha256: sha256(workbookBytes),
      validationReportSha256: sha256(reportBytes),
      reportStatus: report.validation.status,
      formulaRecalculated: report.output.formula_recalculated,
      sourceHashBefore,
      sourceHashAfter: await fileSha256(request.sourcePath),
      temporaryFiles: files.filter((name) => name.endsWith(".tmp")).length,
      journalFiles: (await journalEntries(directory)).length,
      cleanupReceipt: result.cleanup
    };
  } finally {
    await removeTemporaryDirectory(directory);
  }
})();

process.stdout.write(
  `${JSON.stringify({ ...receipt, temporaryDirectoryRemoved: true })}\n`
);
