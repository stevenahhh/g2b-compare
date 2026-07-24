import { createHash } from "node:crypto";
import { readFile, stat } from "node:fs/promises";
import type JSZip from "jszip";
import { wantedCells } from "../inspect/cell-address.js";
import { parseWorksheetCells, readSharedStrings } from "../inspect/cell-values.js";
import { LegacyImportError } from "../inspect/errors.js";
import { inspectOoxmlPackage } from "../inspect/ooxml.js";
import { assertProfileMatchesInspection } from "../inspect/profile.js";
import type { LegacyCellValue, LegacyScalarValue } from "../inspect/types.js";
import { inspectZipPackage, ZIP_LIMITS } from "../inspect/zip.js";
import { zipText } from "../inspect/xml.js";
import { invalidateCalculationMetadata } from "./calc.js";
import { OoxmlPatchError } from "./errors.js";
import { buildPatchPlan, type PlannedCell } from "./plan.js";
import { loadPatchProfile, type PatchProfile } from "./profile.js";
import {
  PatchLegacyWorkbookInputSchema,
  type ChangedCellReceipt,
  type PatchCellCoordinate,
  type PatchLegacyWorkbookInput,
  type PatchedLegacyWorkbook
} from "./types.js";
import {
  comparableValue,
  patchWorksheetXml,
  workbookUsesDate1904
} from "./xml.js";

type SheetWork = {
  readonly sheet: string;
  readonly part: string;
  readonly writes: readonly {
    readonly address: string;
    readonly value: PlannedCell["value"];
  }[];
  readonly changedCells: readonly ChangedCellReceipt[];
};

export async function patchLegacyWorkbook(
  rawInput: PatchLegacyWorkbookInput,
  options: { readonly manifestRoot?: URL } = {}
): Promise<PatchedLegacyWorkbook> {
  const parsed = PatchLegacyWorkbookInputSchema.safeParse(rawInput);
  if (!parsed.success) {
    throw new OoxmlPatchError("PATCH_VALUE_INVALID");
  }
  const bytes = await readSource(parsed.data.source);
  const sourceSha256 = sha256(bytes);
  if (sourceSha256 !== parsed.data.expectedSourceSha256) {
    throw new OoxmlPatchError("STALE_SOURCE");
  }
  const profile = await loadPatchProfile(
    sourceSha256,
    options.manifestRoot
  );
  const inspected = await inspectZipPackage(bytes);
  const ooxml = await inspectOoxmlPackage(inspected);
  assertProfileMatchesInspection(profile, ooxml);
  const plan = buildPatchPlan({
    profile,
    itemCount: parsed.data.itemCount,
    cells: parsed.data.cells
  });
  const workbookXml = await zipText(inspected.archive, "xl/workbook.xml");
  const date1904 = workbookUsesDate1904(workbookXml);
  const work = await prepareSheetWork({
    archive: inspected.archive,
    profile,
    plan,
    date1904
  });
  const changedCells = work.flatMap((sheet) => sheet.changedCells);
  if (changedCells.length === 0) {
    return {
      workbook: new Uint8Array(bytes),
      receipt: {
        schemaVersion: "legacy-ooxml-patch-v1",
        profileId: profile.profileId,
        sourceSha256,
        outputSha256: sourceSha256,
        changedCells: [],
        affectedFormulaCells: [],
        changedParts: []
      }
    };
  }
  const affectedFormulaCells: PatchCellCoordinate[] = [];
  const changedParts = new Set<string>();
  const caches = wantedCells(profile.formulaCacheCells);
  for (const sheet of profile.sheetMap) {
    const sheetWork = work.find((candidate) => candidate.sheet === sheet.name);
    const cacheAddresses = new Set(
      (caches.get(sheet.name) ?? []).map((point) => point.address)
    );
    if (sheetWork === undefined && cacheAddresses.size === 0) {
      continue;
    }
    const sourceXml = await zipText(inspected.archive, sheet.part);
    const patched = patchWorksheetXml({
      xml: sourceXml,
      writes: sheetWork?.writes ?? [],
      cacheAddresses,
      date1904
    });
    if (patched.xml !== sourceXml) {
      replaceArchivePart(inspected.archive, sheet.part, patched.xml);
      changedParts.add(sheet.part);
    }
    patched.affectedCaches.forEach((address) => {
      affectedFormulaCells.push({ sheet: sheet.name, address });
    });
  }
  const metadataParts = await invalidateCalculationMetadata({
    archive: inspected.archive,
    packageDriftAllowlist: profile.packageDriftAllowlist
  });
  metadataParts.forEach((part) => {
    changedParts.add(part);
  });
  const workbook = await inspected.archive.generateAsync({
    type: "uint8array",
    compression: "DEFLATE",
    compressionOptions: { level: 6 },
    platform: "DOS",
    mimeType:
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
  });
  return {
    workbook,
    receipt: {
      schemaVersion: "legacy-ooxml-patch-v1",
      profileId: profile.profileId,
      sourceSha256,
      outputSha256: sha256(workbook),
      changedCells,
      affectedFormulaCells,
      changedParts: [...changedParts].toSorted()
    }
  };
}

type WorkPreparationInput = {
  readonly archive: JSZip;
  readonly profile: PatchProfile;
  readonly plan: readonly PlannedCell[];
  readonly date1904: boolean;
};

async function prepareSheetWork(
  input: WorkPreparationInput
): Promise<readonly SheetWork[]> {
  const sharedStrings = await readSharedStrings(input.archive);
  const work: SheetWork[] = [];
  for (const sheet of input.profile.sheetMap) {
    const planned = input.plan.filter((cell) => cell.sheet === sheet.name);
    if (planned.length === 0) {
      continue;
    }
    const parsed = parseWorksheetCells({
      wanted: new Set(planned.map((cell) => cell.address)),
      sharedStrings,
      xml: await zipText(input.archive, sheet.part)
    });
    const writes: {
      readonly address: string;
      readonly value: PlannedCell["value"];
    }[] = [];
    const changedCells: ChangedCellReceipt[] = [];
    for (const cell of planned) {
      const before = parsed.get(cell.address) ?? { kind: "blank" };
      if (before.kind === "formula") {
        if (cell.explicit) {
          throw new OoxmlPatchError("OOXML_CELL_NOT_OWNED");
        }
        if (!cell.mayClearFormula) {
          continue;
        }
      } else if (
        sameScalar(before, comparableValue(cell.value, input.date1904))
      ) {
        continue;
      }
      writes.push({ address: cell.address, value: cell.value });
      changedCells.push({
        sheet: cell.sheet,
        address: cell.address,
        before,
        after: cell.value
      });
    }
    if (writes.length > 0) {
      work.push({
        sheet: sheet.name,
        part: sheet.part,
        writes,
        changedCells
      });
    }
  }
  return work;
}

function sameScalar(
  before: LegacyCellValue,
  after: LegacyScalarValue
): boolean {
  return before.kind !== "formula" &&
    JSON.stringify(before) === JSON.stringify(after);
}

async function readSource(source: string | URL): Promise<Uint8Array> {
  try {
    const sourceStat = await stat(source);
    if (
      !sourceStat.isFile() ||
      sourceStat.size > ZIP_LIMITS.maxSourceBytes
    ) {
      throw new LegacyImportError("ZIP_LIMIT_EXCEEDED");
    }
    const bytes = await readFile(source);
    if (bytes.byteLength > ZIP_LIMITS.maxSourceBytes) {
      throw new LegacyImportError("ZIP_LIMIT_EXCEEDED");
    }
    return bytes;
  } catch (error) {
    if (error instanceof LegacyImportError) {
      throw error;
    }
    throw new LegacyImportError("UNSUPPORTED_WORKBOOK");
  }
}

function replaceArchivePart(
  archive: JSZip,
  part: string,
  xml: string
): void {
  const entry = archive.files[part];
  if (entry === undefined || entry.dir) {
    throw new LegacyImportError("CORRUPT_OOXML");
  }
  archive.file(part, xml, {
    createFolders: false,
    date: entry.date
  });
}

function sha256(value: Uint8Array): string {
  return createHash("sha256").update(value).digest("hex");
}
