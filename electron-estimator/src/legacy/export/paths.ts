import { readFile, stat } from "node:fs/promises";
import {
  dirname,
  isAbsolute,
  normalize,
  relative,
  resolve
} from "node:path";
import { AtomicExportError } from "./types.js";

export type ExportPaths = {
  readonly source: string;
  readonly workbook: string;
  readonly report: string;
  readonly workbookTemporary: string;
  readonly reportTemporary: string;
};

export function exportPaths(input: {
  readonly source: string;
  readonly workbook: string;
  readonly transactionDirectory: string;
  readonly transactionId: string;
}): ExportPaths {
  const report = input.workbook.replace(/[.]xlsx$/u, ".validation.json");
  return {
    source: input.source,
    workbook: input.workbook,
    report,
    workbookTemporary: resolve(
      input.transactionDirectory,
      `${input.transactionId}.workbook.tmp`
    ),
    reportTemporary: resolve(
      input.transactionDirectory,
      `${input.transactionId}.report.tmp`
    )
  };
}

export function journalRootIsOutsideDestination(
  journalRoot: string,
  destinationDirectory: string
): boolean {
  if (!isAbsolute(journalRoot)) {
    return false;
  }
  const relation = relative(
    normalize(resolve(destinationDirectory)),
    normalize(resolve(journalRoot))
  );
  return relation !== "" &&
    (relation.startsWith("..") || isAbsolute(relation));
}

export async function preflightExportPaths(
  paths: ExportPaths,
  expectedSourceSha256: string,
  hash: (bytes: Uint8Array) => string
): Promise<Uint8Array> {
  if (caseInsensitivePath(paths.source) === caseInsensitivePath(paths.workbook)) {
    throw new AtomicExportError("SOURCE_DESTINATION_CONFLICT");
  }
  const sourceStat = await stat(paths.source);
  const directoryStat = await stat(dirname(paths.workbook));
  if (!sourceStat.isFile() || !directoryStat.isDirectory()) {
    throw new AtomicExportError("ATOMIC_EXPORT_ABORTED");
  }
  const workbookStat = await statIfExists(paths.workbook);
  if (workbookStat !== undefined) {
    if (
      sourceStat.dev === workbookStat.dev &&
      sourceStat.ino === workbookStat.ino
    ) {
      throw new AtomicExportError("SOURCE_DESTINATION_CONFLICT");
    }
    throw new AtomicExportError("DESTINATION_EXISTS");
  }
  if (await statIfExists(paths.report) !== undefined) {
    throw new AtomicExportError("DESTINATION_EXISTS");
  }
  const sourceBytes = await readFile(paths.source);
  if (hash(sourceBytes) !== expectedSourceSha256) {
    throw new AtomicExportError("ATOMIC_EXPORT_ABORTED");
  }
  return sourceBytes;
}

export async function statIfExists(
  path: string
): Promise<Awaited<ReturnType<typeof stat>> | undefined> {
  try {
    return await stat(path);
  } catch (error) {
    if (
      error instanceof Error &&
      "code" in error &&
      error.code === "ENOENT"
    ) {
      return undefined;
    }
    throw error;
  }
}

function caseInsensitivePath(path: string): string {
  return normalize(resolve(path)).toLocaleLowerCase("en-US");
}
