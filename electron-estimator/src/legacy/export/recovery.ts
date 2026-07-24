import { readFile, readdir, rename, rm } from "node:fs/promises";
import type { Dirent } from "node:fs";
import { resolve } from "node:path";
import {
  DEFAULT_JOURNAL_ROOT,
  parseJournal,
  type JournalRecord
} from "./journal.js";
import { statIfExists } from "./paths.js";
import { recoveryProofMatches } from "./recovery-proof.js";
import { ATOMIC_EXPORT_ERROR_MESSAGES } from "./types.js";

export type RecoveryOptions = {
  readonly journalRoot?: string;
};

export type RecoveryReceipt = {
  readonly scannedTransactions: number;
  readonly recoveredTransactions: number;
  readonly preservedTransactions: number;
  readonly rejectedTransactions: number;
  readonly corruptJournalsRemoved: number;
  readonly cleanupComplete: boolean;
};

export type RecoveryResult =
  | { readonly ok: true; readonly receipt: RecoveryReceipt }
  | {
      readonly ok: false;
      readonly error: {
        readonly code: "ATOMIC_EXPORT_ABORTED";
        readonly message: typeof ATOMIC_EXPORT_ERROR_MESSAGES.ATOMIC_EXPORT_ABORTED;
      };
      readonly receipt: RecoveryReceipt;
    };

type RecoveryOutcome = "recovered" | "preserved" | "rejected";

const TRANSACTION_ID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;

export async function recoverInterruptedExports(
  options: RecoveryOptions = {}
): Promise<RecoveryResult> {
  const journalRoot = resolve(
    options.journalRoot ?? DEFAULT_JOURNAL_ROOT
  );
  const receipt = {
    scannedTransactions: 0,
    recoveredTransactions: 0,
    preservedTransactions: 0,
    rejectedTransactions: 0,
    corruptJournalsRemoved: 0,
    cleanupComplete: true
  };
  let entries: readonly Dirent<string>[];
  try {
    entries = await readdir(journalRoot, { withFileTypes: true });
  } catch (error) {
    if (
      error instanceof Error &&
      "code" in error &&
      error.code === "ENOENT"
    ) {
      return { ok: true, receipt };
    }
    if (error instanceof Error) {
      return recoveryFailure({ ...receipt, cleanupComplete: false });
    }
    throw error;
  }
  for (const entry of entries.toSorted((left, right) =>
    left.name.localeCompare(right.name)
  )) {
    if (!entry.isDirectory() || !TRANSACTION_ID_PATTERN.test(entry.name)) {
      continue;
    }
    receipt.scannedTransactions += 1;
    const directory = resolve(journalRoot, entry.name);
    const journalPath = resolve(directory, "journal.jsonl");
    let bytes: Uint8Array;
    try {
      bytes = await readFile(journalPath);
    } catch (error) {
      if (error instanceof Error) {
        reject(receipt);
        continue;
      }
      throw error;
    }
    const parsed = parseJournal(bytes, {
      transactionId: entry.name,
      transactionDirectory: directory
    });
    switch (parsed.kind) {
      case "corrupt":
        reject(receipt);
        break;
      case "tracked": {
        const outcome = parsed.damaged
          ? "rejected"
          : await recoverTracked(parsed.record);
        recordOutcome(receipt, outcome);
        break;
      }
      default:
        assertNever(parsed);
    }
  }
  return receipt.cleanupComplete
    ? { ok: true, receipt }
    : recoveryFailure(receipt);
}

async function recoverTracked(
  record: JournalRecord
): Promise<RecoveryOutcome> {
  const workbookExists =
    await statIfExists(record.paths.workbook) !== undefined;
  const reportExists =
    await statIfExists(record.paths.report) !== undefined;
  if (!workbookExists && !reportExists) {
    return await removeOwnedTransaction(record.transactionDirectory)
      ? "recovered"
      : "rejected";
  }
  if (!reportExists) {
    return "rejected";
  }
  const proofPath = workbookExists
    ? record.paths.workbook
    : record.paths.workbookTemporary;
  if (!await recoveryProofMatches(record, proofPath)) {
    return "rejected";
  }
  if (!workbookExists) {
    try {
      await rename(record.paths.workbookTemporary, record.paths.workbook);
    } catch (error) {
      if (error instanceof Error) {
        return "rejected";
      }
      throw error;
    }
  }
  if (!await removeOwnedTransaction(record.transactionDirectory)) {
    return "rejected";
  }
  return record.state === "committed" ? "preserved" : "recovered";
}

async function removeOwnedTransaction(path: string): Promise<boolean> {
  try {
    await rm(path, { recursive: true });
    return true;
  } catch (error) {
    if (error instanceof Error) {
      return false;
    }
    throw error;
  }
}

function recordOutcome(
  receipt: {
    recoveredTransactions: number;
    preservedTransactions: number;
    rejectedTransactions: number;
    cleanupComplete: boolean;
  },
  outcome: RecoveryOutcome
): void {
  switch (outcome) {
    case "recovered":
      receipt.recoveredTransactions += 1;
      break;
    case "preserved":
      receipt.preservedTransactions += 1;
      break;
    case "rejected":
      reject(receipt);
      break;
    default:
      assertNever(outcome);
  }
}

function reject(receipt: {
  rejectedTransactions: number;
  cleanupComplete: boolean;
}): void {
  receipt.rejectedTransactions += 1;
  receipt.cleanupComplete = false;
}

function recoveryFailure(
  receipt: RecoveryReceipt
): RecoveryResult {
  return {
    ok: false,
    error: {
      code: "ATOMIC_EXPORT_ABORTED",
      message: ATOMIC_EXPORT_ERROR_MESSAGES.ATOMIC_EXPORT_ABORTED
    },
    receipt
  };
}

function assertNever(value: never): never {
  throw new TypeError(`Unexpected recovery variant: ${String(value)}`);
}
