import { createHash } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import { resolve } from "node:path";
import JSZip from "jszip";
import type {
  ValidationReportRequest,
  ValidationReportSuccess
} from "../../src/legacy/validation/index.js";

const DATASET = resolve(import.meta.dirname, "..", "..", "..", "dataset");
const MANIFEST_ROOT = resolve(
  import.meta.dirname,
  "..",
  "..",
  "resources",
  "manifests",
  "legacy"
);
const SCENARIOS = {
  A: {
    hash: "445012e259ab5318a1d52468cce93ee28a55a8bcb467876f40a47a939e4668db",
    manifest: "gwangyang-direct-2025.json"
  },
  B: {
    hash: "2220cd9936ebdf908d64c0571a4c8de83973eaa89c6778a64afec07de7c5e701",
    manifest: "suncheon-procurement-2025.json"
  },
  C: {
    hash: "8a55700bdaf62a00c208c7286531fd56ca321571f73f7620505a823ef5d4d0f1",
    manifest: "gwangyang-procurement-final-2025.json"
  }
} as const;

export type ScenarioId = keyof typeof SCENARIOS;

export async function scenarioRequest(
  id: ScenarioId
): Promise<ValidationReportRequest> {
  const scenario = SCENARIOS[id];
  const source = await scenarioSourcePath(id);
  const originalBytes = await readFile(source);
  const manifestBytes = await readFile(
    resolve(MANIFEST_ROOT, scenario.manifest)
  );
  const manifest: unknown = JSON.parse(
    new TextDecoder("utf-8", { fatal: true }).decode(manifestBytes)
  );
  if (
    typeof manifest !== "object" ||
    manifest === null ||
    !("source" in manifest) ||
    typeof manifest.source !== "object" ||
    manifest.source === null ||
    !("filename" in manifest.source) ||
    typeof manifest.source.filename !== "string"
  ) {
    throw new TypeError(`Invalid scenario manifest ${id}`);
  }
  return {
    originalBytes,
    outputBytes: originalBytes,
    manifestBytes,
    patchReceipt: {
      changedCells: [],
      changedParts: []
    },
    outputFilename: manifest.source.filename.replace(
      /[.]xlsx$/iu,
      "_검토초안_미재계산.xlsx"
    ),
    generatedAtUtc: "2026-07-23T12:00:00.000Z",
    build: {
      appVersion: "0.1.0",
      commitSha256:
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      signed: false
    },
    officialSources: []
  };
}

export async function scenarioSourcePath(id: ScenarioId): Promise<string> {
  const scenario = SCENARIOS[id];
  for (const filename of await readdir(DATASET)) {
    const candidate = await readFile(resolve(DATASET, filename));
    if (sha256(candidate) === scenario.hash) {
      return resolve(DATASET, filename);
    }
  }
  throw new TypeError(`Missing scenario ${id}`);
}

export async function mutateCell(
  bytes: Uint8Array,
  part: string,
  address: string,
  mutate: (cellXml: string) => string
): Promise<Uint8Array> {
  return mutatePart(bytes, part, (xml) => {
    const pattern = new RegExp(
      `<c(?=[^>]*\\br="${address}")(?:[^<]|<(?!c\\b))*?</c>`,
      "u"
    );
    const cell = xml.match(pattern)?.[0];
    if (cell === undefined) {
      throw new TypeError(`Missing cell ${address}`);
    }
    return xml.replace(cell, mutate(cell));
  });
}

export async function mutatePart(
  bytes: Uint8Array,
  part: string,
  mutate: (content: string) => string
): Promise<Uint8Array> {
  const archive = await JSZip.loadAsync(bytes);
  const entry = archive.file(part);
  if (entry === null) {
    throw new TypeError(`Missing part ${part}`);
  }
  archive.file(part, mutate(await entry.async("string")));
  return archive.generateAsync({
    type: "uint8array",
    compression: "DEFLATE"
  });
}

export async function addPart(
  bytes: Uint8Array,
  part: string,
  content: string | Uint8Array
): Promise<Uint8Array> {
  const archive = await JSZip.loadAsync(bytes);
  archive.file(part, content);
  return archive.generateAsync({
    type: "uint8array",
    compression: "DEFLATE"
  });
}

export function expectSuccess(
  result:
    | ValidationReportSuccess
    | { readonly ok: false; readonly errors: readonly string[] }
): ValidationReportSuccess {
  if (!result.ok) {
    throw new TypeError(`Expected success: ${result.errors.join(",")}`);
  }
  return result;
}

export function sha256(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex");
}
