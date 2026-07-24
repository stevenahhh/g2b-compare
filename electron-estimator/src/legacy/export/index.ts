import { createHash, randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { basename, dirname } from "node:path";
import { patchLegacyWorkbook } from "../patch/index.js";
import { buildValidationReport } from "../validation/index.js";
import {
  beforeDeadline,
  cleanupPublication,
  newPublicationState,
  publishTemporary,
  runStage,
  writeDurableTemporary
} from "./files.js";
import { exportPaths, journalRootIsOutsideDestination, preflightExportPaths } from "./paths.js";
import {
  AtomicExportError,
  AtomicLegacyExportRequestSchema,
  type AtomicExportOptions,
  type AtomicLegacyExportResult
} from "./types.js";
import {
  appendJournal,
  DEFAULT_JOURNAL_ROOT,
  journalTransaction,
  removeTransaction,
  transactionDirectory,
  type JournalTransaction
} from "./journal.js";
import { cleanupReceipt, exportFailure, exportSuccess } from "./result.js";
import {
  recoverInterruptedExports,
  type RecoveryOptions
} from "./recovery.js";
import { verifyTemporaryPair } from "./verify.js";
export {
  ATOMIC_EXPORT_ERROR_MESSAGES,
  ATOMIC_EXPORT_STAGES,
  LEGACY_EXPORT_DISCLAIMER_VERSION
} from "./types.js";
export type {
  AtomicCleanupReceipt,
  AtomicExportErrorCode,
  AtomicExportOptions,
  AtomicExportStage,
  AtomicLegacyExportFailure,
  AtomicLegacyExportRequest,
  AtomicLegacyExportResult,
  AtomicLegacyExportSuccess
} from "./types.js";
export {
  recoverInterruptedExports
} from "./recovery.js";
export type {
  RecoveryOptions,
  RecoveryReceipt,
  RecoveryResult
} from "./recovery.js";
const DEFAULT_TIMEOUT_MS = 120_000;

export async function exportLegacyWorkbook(
  rawRequest: unknown,
  options: AtomicExportOptions = {}
): Promise<AtomicLegacyExportResult> {
  const state = newPublicationState();
  const recoveryOptions: RecoveryOptions = options.journalRoot === undefined
    ? {}
    : { journalRoot: options.journalRoot };
  const recovery = await recoverInterruptedExports(recoveryOptions);
  if (!recovery.ok) {
    return exportFailure("ATOMIC_EXPORT_ABORTED", cleanupReceipt(state));
  }
  const parsed = AtomicLegacyExportRequestSchema.safeParse(rawRequest);
  if (!parsed.success) {
    return exportFailure("INVALID_EXPORT_REQUEST", cleanupReceipt(state));
  }
  if (!parsed.data.disclaimer.checked) {
    return exportFailure(
      "EXPORT_DISCLAIMER_REQUIRED",
      cleanupReceipt(state)
    );
  }
  const request = parsed.data;
  const transactionId = randomUUID();
  const journalRoot = options.journalRoot ?? DEFAULT_JOURNAL_ROOT;
  const paths = exportPaths({
    source: request.sourcePath,
    workbook: request.destinationPath,
    transactionDirectory: transactionDirectory(journalRoot, transactionId),
    transactionId
  });
  if (
    !journalRootIsOutsideDestination(
      journalRoot,
      dirname(paths.workbook)
    )
  ) {
    return exportFailure("INVALID_EXPORT_REQUEST", cleanupReceipt(state));
  }
  const signal = AbortSignal.timeout(options.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  let transaction: JournalTransaction | undefined;
  try {
    const sourceBytes = await beforeDeadline(
      preflightExportPaths(
        paths,
        request.expectedSourceSha256,
        sha256
      ),
      signal
    );
    await runStage("patch", options, signal);
    const patched = await beforeDeadline(
      patchLegacyWorkbook({
        source: request.sourcePath,
        expectedSourceSha256: request.expectedSourceSha256,
        itemCount: request.itemCount,
        cells: request.cells
      }, options.manifestRoot === undefined
        ? {}
        : { manifestRoot: options.manifestRoot }),
      signal
    );
    await runStage("validation", options, signal);
    const validation = await beforeDeadline(
      buildValidationReport({
        originalBytes: sourceBytes,
        outputBytes: patched.workbook,
        manifestBytes: request.manifestBytes,
        patchReceipt: patched.receipt,
        outputFilename: basename(paths.workbook),
        generatedAtUtc: request.generatedAtUtc,
        build: request.build,
        officialSources: request.officialSources
      }),
      signal
    );
    if (!validation.ok || validation.reportSha256 !== sha256(validation.reportBytes)) {
      throw new AtomicExportError("ATOMIC_EXPORT_ABORTED");
    }
    const activeTransaction = journalTransaction({
      paths,
      journalRoot,
      transactionId,
      proof: {
        outputFilename: basename(paths.workbook),
        sourceSha256: request.expectedSourceSha256,
        templateSha256: validation.report.template.workbook_sha256,
        outputSha256: validation.report.output.workbook_sha256,
        reportSha256: validation.reportSha256
      }
    });
    transaction = activeTransaction;
    const recordState = (
      state: Parameters<typeof appendJournal>[0]["state"],
      create = false
    ) => appendJournal({
      transaction: activeTransaction,
      state,
      create,
      signal
    });
    await runStage("journal-prepare", options, signal);
    await recordState("preparing", true);
    await writeDurableTemporary({
      path: paths.workbookTemporary,
      bytes: patched.workbook,
      kind: "workbook",
      signal,
      options,
      state
    });
    await writeDurableTemporary({
      path: paths.reportTemporary,
      bytes: validation.reportBytes,
      kind: "report",
      signal,
      options,
      state
    });
    const {
      workbookSha256,
      validationReportSha256
    } = await verifyTemporaryPair({
      paths,
      patched,
      validation,
      options,
      signal
    });
    if (sha256(await beforeDeadline(readFile(paths.source), signal)) !==
      request.expectedSourceSha256) {
      throw new AtomicExportError("ATOMIC_EXPORT_ABORTED");
    }
    await runStage("journal-staged", options, signal);
    await recordState("staged");
    await runStage("journal-before-report", options, signal);
    await recordState("report-publishing");
    await publishTemporary({
      kind: "report",
      paths,
      options,
      signal,
      state
    });
    await runStage("journal-before-workbook", options, signal);
    await recordState("workbook-publishing");
    await publishTemporary({
      kind: "workbook",
      paths,
      options,
      signal,
      state
    });
    if (sha256(await beforeDeadline(readFile(paths.source), signal)) !==
      request.expectedSourceSha256) {
      throw new AtomicExportError("ATOMIC_EXPORT_ABORTED");
    }
    await runStage("journal-commit", options, signal);
    await recordState("committed");
    if (!await removeTransaction(activeTransaction)) {
      throw new AtomicExportError("ATOMIC_EXPORT_ABORTED");
    }
    transaction = undefined;
    return exportSuccess({
      request,
      workbookName: basename(paths.workbook),
      validationReportName: basename(paths.report),
      workbookSha256,
      validationReportSha256,
      cleanup: cleanupReceipt(state)
    });
  } catch (error) {
    await cleanupPublication(paths, state);
    if (
      transaction !== undefined &&
      state.cleanupComplete &&
      !await removeTransaction(transaction)
    ) {
      state.cleanupComplete = false;
    }
    const code = error instanceof AtomicExportError
      ? error.code
      : "ATOMIC_EXPORT_ABORTED";
    return exportFailure(code, cleanupReceipt(state));
  }
}
function sha256(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex");
}
