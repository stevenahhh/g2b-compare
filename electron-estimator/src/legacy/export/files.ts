import {
  open,
  readFile,
  rename,
  unlink
} from "node:fs/promises";
import { statIfExists, type ExportPaths } from "./paths.js";
import { AtomicExportError, type AtomicExportOptions } from "./types.js";

export type PublicationState = {
  workbookTemporaryExists: boolean;
  reportTemporaryExists: boolean;
  workbookFinalExists: boolean;
  reportFinalExists: boolean;
  temporaryFilesCreated: number;
  temporaryFilesRemoved: number;
  finalFilesPublished: number;
  finalFilesRolledBack: number;
  cleanupComplete: boolean;
};

export async function writeDurableTemporary(
  input: {
    readonly path: string;
    readonly bytes: Uint8Array;
    readonly kind: "workbook" | "report";
    readonly signal: AbortSignal;
    readonly options: AtomicExportOptions;
    readonly state: PublicationState;
  }
): Promise<void> {
  const handle = await open(input.path, "wx", 0o600);
  markTemporaryCreated(input.kind, input.state);
  try {
    await runStage(`${input.kind}-write`, input.options, input.signal);
    await beforeDeadline(
      handle.writeFile(input.bytes, { signal: input.signal }),
      input.signal
    );
    await runStage(`${input.kind}-sync`, input.options, input.signal);
    await beforeDeadline(handle.sync(), input.signal);
    await runStage(`${input.kind}-close`, input.options, input.signal);
  } finally {
    await handle.close();
  }
}

export async function verifyTemporary(
  path: string,
  expected: Uint8Array,
  signal: AbortSignal
): Promise<Uint8Array> {
  const actual = await beforeDeadline(readFile(path), signal);
  if (
    actual.byteLength !== expected.byteLength ||
    actual.some((byte, index) => byte !== expected[index])
  ) {
    throw new AtomicExportError("ATOMIC_EXPORT_ABORTED");
  }
  return actual;
}

export async function publishTemporary(
  input: {
    readonly kind: "workbook" | "report";
    readonly paths: ExportPaths;
    readonly options: AtomicExportOptions;
    readonly signal: AbortSignal;
    readonly state: PublicationState;
  }
): Promise<void> {
  const temporary = input.kind === "workbook"
    ? input.paths.workbookTemporary
    : input.paths.reportTemporary;
  const final = input.kind === "workbook"
    ? input.paths.workbook
    : input.paths.report;
  if (await statIfExists(final) !== undefined) {
    throw new AtomicExportError("DESTINATION_EXISTS");
  }
  await runStage(`rename-${input.kind}`, input.options, input.signal);
  await beforeDeadline(rename(temporary, final), input.signal);
  if (input.kind === "workbook") {
    input.state.workbookTemporaryExists = false;
    input.state.workbookFinalExists = true;
  } else {
    input.state.reportTemporaryExists = false;
    input.state.reportFinalExists = true;
  }
  input.state.temporaryFilesRemoved += 1;
  input.state.finalFilesPublished += 1;
}

export async function cleanupPublication(
  paths: ExportPaths,
  state: PublicationState
): Promise<void> {
  await removeTracked({
    path: paths.report,
    exists: state.reportFinalExists,
    removed: () => {
      state.reportFinalExists = false;
      state.finalFilesRolledBack += 1;
    },
    state
  });
  await removeTracked({
    path: paths.workbook,
    exists: state.workbookFinalExists,
    removed: () => {
      state.workbookFinalExists = false;
      state.finalFilesRolledBack += 1;
    },
    state
  });
  await removeTracked({
    path: paths.reportTemporary,
    exists: state.reportTemporaryExists,
    removed: () => {
      state.reportTemporaryExists = false;
      state.temporaryFilesRemoved += 1;
    },
    state
  });
  await removeTracked({
    path: paths.workbookTemporary,
    exists: state.workbookTemporaryExists,
    removed: () => {
      state.workbookTemporaryExists = false;
      state.temporaryFilesRemoved += 1;
    },
    state
  });
}

export async function runStage(
  stage: Parameters<NonNullable<AtomicExportOptions["beforeStage"]>>[0],
  options: AtomicExportOptions,
  signal: AbortSignal
): Promise<void> {
  await beforeDeadline(
    options.beforeStage?.(stage) ?? Promise.resolve(),
    signal
  );
}

export async function beforeDeadline<T>(
  operation: Promise<T>,
  signal: AbortSignal
): Promise<T> {
  if (signal.aborted) {
    throw new AtomicExportError("ATOMIC_EXPORT_ABORTED");
  }
  return new Promise<T>((resolvePromise, rejectPromise) => {
    const abort = () => {
      rejectPromise(new AtomicExportError("ATOMIC_EXPORT_ABORTED"));
    };
    signal.addEventListener("abort", abort, { once: true });
    operation.then(
      (value) => {
        signal.removeEventListener("abort", abort);
        resolvePromise(value);
      },
      (error: unknown) => {
        signal.removeEventListener("abort", abort);
        rejectPromise(error);
      }
    );
  });
}

export function newPublicationState(): PublicationState {
  return {
    workbookTemporaryExists: false,
    reportTemporaryExists: false,
    workbookFinalExists: false,
    reportFinalExists: false,
    temporaryFilesCreated: 0,
    temporaryFilesRemoved: 0,
    finalFilesPublished: 0,
    finalFilesRolledBack: 0,
    cleanupComplete: true
  };
}

function markTemporaryCreated(
  kind: "workbook" | "report",
  state: PublicationState
): void {
  if (kind === "workbook") {
    state.workbookTemporaryExists = true;
  } else {
    state.reportTemporaryExists = true;
  }
  state.temporaryFilesCreated += 1;
}

async function removeTracked(input: {
  readonly path: string;
  readonly exists: boolean;
  readonly removed: () => void;
  readonly state: PublicationState;
}): Promise<void> {
  if (!input.exists) {
    return;
  }
  try {
    await unlink(input.path);
    input.removed();
  } catch (error) {
    if (error instanceof Error) {
      input.state.cleanupComplete = false;
      return;
    }
    throw error;
  }
}
