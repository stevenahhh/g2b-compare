import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { basename } from "node:path";
import { parseValidationReportBytes } from "../validation/index.js";
import type { JournalRecord } from "./journal.js";

export async function recoveryProofMatches(
  record: JournalRecord,
  workbookPath: string
): Promise<boolean> {
  let reportBytes: Uint8Array;
  let sourceBytes: Uint8Array;
  let workbookBytes: Uint8Array;
  try {
    [reportBytes, sourceBytes, workbookBytes] = await Promise.all([
      readFile(record.paths.report),
      readFile(record.paths.source),
      readFile(workbookPath)
    ]);
  } catch (error) {
    if (error instanceof Error) {
      return false;
    }
    throw error;
  }
  let report: ReturnType<typeof parseValidationReportBytes>;
  try {
    report = parseValidationReportBytes(reportBytes);
  } catch (error) {
    if (error instanceof Error) {
      return false;
    }
    throw error;
  }
  return sha256(reportBytes) === record.proof.reportSha256 &&
    sha256(sourceBytes) === record.proof.sourceSha256 &&
    record.proof.sourceSha256 === record.proof.templateSha256 &&
    report.template.workbook_sha256 === record.proof.templateSha256 &&
    sha256(workbookBytes) === record.proof.outputSha256 &&
    report.output.workbook_sha256 === record.proof.outputSha256 &&
    report.output.filename === record.proof.outputFilename &&
    report.output.filename === basename(record.paths.workbook);
}

function sha256(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex");
}
