import { mkdir, open, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import {
  basename,
  dirname,
  isAbsolute,
  normalize,
  resolve
} from "node:path";
import { z } from "zod";
import { beforeDeadline } from "./files.js";
import type { ExportPaths } from "./paths.js";

export const DEFAULT_JOURNAL_ROOT = resolve(
  tmpdir(),
  "electron-estimator-atomic-export-journal"
);

export const JOURNAL_STATES = [
  "preparing",
  "staged",
  "report-publishing",
  "workbook-publishing",
  "committed"
] as const;

export type JournalState = (typeof JOURNAL_STATES)[number];

const Sha256Schema = z.string().regex(/^[0-9a-f]{64}$/u);
const JournalPathsSchema = z.strictObject({
  source: z.string().min(1),
  workbook: z.string().min(1),
  report: z.string().min(1),
  workbookTemporary: z.string().min(1),
  reportTemporary: z.string().min(1)
});
const JournalProofSchema = z.strictObject({
  outputFilename: z.string().min(1),
  sourceSha256: Sha256Schema,
  templateSha256: Sha256Schema,
  outputSha256: Sha256Schema,
  reportSha256: Sha256Schema
});
const JournalRecordSchema = z.strictObject({
  schemaVersion: z.literal("atomic-legacy-export-journal-v2"),
  transactionId: z.string().uuid(),
  transactionDirectory: z.string().min(1),
  state: z.enum(JOURNAL_STATES),
  paths: JournalPathsSchema,
  proof: JournalProofSchema
});

export type JournalProof = z.output<typeof JournalProofSchema>;
export type JournalRecord = z.output<typeof JournalRecordSchema>;

export type JournalTransaction = {
  readonly transactionId: string;
  readonly journalRoot: string;
  readonly transactionDirectory: string;
  readonly journalPath: string;
  readonly paths: ExportPaths;
  readonly proof: JournalProof;
};

export type JournalParseResult =
  | {
      readonly kind: "tracked";
      readonly record: JournalRecord;
      readonly damaged: boolean;
    }
  | { readonly kind: "corrupt" };

export function transactionDirectory(
  journalRoot: string,
  transactionId: string
): string {
  return resolve(journalRoot, transactionId);
}

export function journalTransaction(input: {
  readonly paths: ExportPaths;
  readonly journalRoot: string;
  readonly transactionId: string;
  readonly proof: JournalProof;
}): JournalTransaction {
  const directory = transactionDirectory(
    input.journalRoot,
    input.transactionId
  );
  return {
    transactionId: input.transactionId,
    journalRoot: resolve(input.journalRoot),
    transactionDirectory: directory,
    journalPath: resolve(directory, "journal.jsonl"),
    paths: input.paths,
    proof: input.proof
  };
}

export async function appendJournal(input: {
  readonly transaction: JournalTransaction;
  readonly state: JournalState;
  readonly create: boolean;
  readonly signal: AbortSignal;
}): Promise<void> {
  if (input.create) {
    await beforeDeadline(
      mkdir(input.transaction.transactionDirectory, { recursive: true }),
      input.signal
    );
  }
  const handle = await beforeDeadline(
    open(
      input.transaction.journalPath,
      input.create ? "wx" : "a",
      0o600
    ),
    input.signal
  );
  const record = {
    schemaVersion: "atomic-legacy-export-journal-v2",
    transactionId: input.transaction.transactionId,
    transactionDirectory: input.transaction.transactionDirectory,
    state: input.state,
    paths: input.transaction.paths,
    proof: input.transaction.proof
  } satisfies JournalRecord;
  const bytes = new TextEncoder().encode(`${JSON.stringify(record)}\n`);
  try {
    await beforeDeadline(
      handle.writeFile(bytes, { signal: input.signal }),
      input.signal
    );
    await beforeDeadline(handle.sync(), input.signal);
  } finally {
    await handle.close();
  }
}

export async function removeTransaction(
  transaction: JournalTransaction
): Promise<boolean> {
  try {
    await rm(transaction.transactionDirectory, { recursive: true });
    return true;
  } catch (error) {
    if (
      error instanceof Error &&
      "code" in error &&
      error.code === "ENOENT"
    ) {
      return true;
    }
    if (error instanceof Error) {
      return false;
    }
    throw error;
  }
}

export function parseJournal(
  bytes: Uint8Array,
  context: {
    readonly transactionId: string;
    readonly transactionDirectory: string;
  }
): JournalParseResult {
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch (error) {
    if (error instanceof Error) {
      return { kind: "corrupt" };
    }
    throw error;
  }
  let latest: JournalRecord | undefined;
  let damaged = false;
  for (const line of text.split("\n")) {
    if (line === "") {
      continue;
    }
    let value: unknown;
    try {
      value = JSON.parse(line);
    } catch (error) {
      if (error instanceof Error) {
        damaged = true;
        break;
      }
      throw error;
    }
    const parsed = JournalRecordSchema.safeParse(value);
    if (
      !parsed.success ||
      !safeJournalRecord(parsed.data, context) ||
      (latest !== undefined &&
        (latest.transactionId !== parsed.data.transactionId ||
          JSON.stringify(latest.paths) !== JSON.stringify(parsed.data.paths) ||
          JSON.stringify(latest.proof) !== JSON.stringify(parsed.data.proof)))
    ) {
      damaged = true;
      break;
    }
    latest = parsed.data;
  }
  return latest === undefined
    ? { kind: "corrupt" }
    : { kind: "tracked", record: latest, damaged };
}

function safeJournalRecord(
  record: JournalRecord,
  context: {
    readonly transactionId: string;
    readonly transactionDirectory: string;
  }
): boolean {
  const { paths, proof } = record;
  const expectedDirectory = normalize(resolve(context.transactionDirectory));
  return record.transactionId === context.transactionId &&
    record.transactionDirectory === expectedDirectory &&
    Object.values(paths).every(isNormalizedAbsolutePath) &&
    dirname(paths.workbook) === dirname(paths.report) &&
    dirname(paths.workbook) !== expectedDirectory &&
    paths.report ===
      paths.workbook.replace(/[.]xlsx$/u, ".validation.json") &&
    basename(paths.workbook) === proof.outputFilename &&
    /_검토초안_미재계산[.]xlsx$/u.test(proof.outputFilename) &&
    paths.workbookTemporary === resolve(
      expectedDirectory,
      `${record.transactionId}.workbook.tmp`
    ) &&
    paths.reportTemporary === resolve(
      expectedDirectory,
      `${record.transactionId}.report.tmp`
    );
}

function isNormalizedAbsolutePath(path: string): boolean {
  return isAbsolute(path) &&
    normalize(resolve(path)) === path;
}
