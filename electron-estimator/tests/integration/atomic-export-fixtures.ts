import { createHash } from "node:crypto";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join } from "node:path";
import type {
  AtomicExportOptions,
  AtomicLegacyExportRequest
} from "../../src/legacy/export/index.js";
import {
  scenarioRequest,
  scenarioSourcePath,
  type ScenarioId
} from "./validation-report-fixtures.js";

const ITEM_COUNTS = { A: 16, B: 9, C: 24 } as const;
const PATCH_CELLS = {
  A: [{
    sheet: "자재내역서",
    address: "G9",
    value: { kind: "number", value: "987654" }
  }],
  B: [{
    sheet: "단가조사",
    address: "H5",
    value: { kind: "number", value: "987654" }
  }],
  C: [{
    sheet: "단가조사",
    address: "H5",
    value: { kind: "number", value: "987654" }
  }]
} as const;

export async function exportFixture(
  id: ScenarioId,
  directory: string,
  stem = `profile-${id}`
): Promise<AtomicLegacyExportRequest> {
  const validation = await scenarioRequest(id);
  return {
    sourcePath: await scenarioSourcePath(id),
    destinationPath: join(
      directory,
      `${stem}_검토초안_미재계산.xlsx`
    ),
    expectedSourceSha256: sha256(validation.originalBytes),
    itemCount: ITEM_COUNTS[id],
    cells: PATCH_CELLS[id],
    manifestBytes: validation.manifestBytes,
    generatedAtUtc: validation.generatedAtUtc,
    build: validation.build,
    officialSources: validation.officialSources,
    disclaimer: {
      checked: true,
      version: "legacy-export-disclaimer-v1"
    }
  };
}

export async function temporaryExportDirectory(): Promise<string> {
  return mkdtemp(join(tmpdir(), "electron-estimator-atomic-"));
}

export async function removeTemporaryDirectory(
  directory: string
): Promise<void> {
  await Promise.all([
    rm(directory, { recursive: true, force: true }),
    rm(journalRootFor(directory), { recursive: true, force: true })
  ]);
}

export function exportOptions(
  directory: string,
  options: Omit<AtomicExportOptions, "journalRoot"> = {}
): AtomicExportOptions {
  return { ...options, journalRoot: journalRootFor(directory) };
}

export function journalRootFor(directory: string): string {
  return join(dirname(directory), `${basename(directory)}-journal`);
}

export async function journalEntries(
  directory: string
): Promise<readonly string[]> {
  try {
    return await readdir(journalRootFor(directory));
  } catch (error) {
    if (
      error instanceof Error &&
      "code" in error &&
      error.code === "ENOENT"
    ) {
      return [];
    }
    throw error;
  }
}

export async function fileSha256(path: string): Promise<string> {
  return sha256(await readFile(path));
}

export function sha256(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex");
}
