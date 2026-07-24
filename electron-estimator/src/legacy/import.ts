import { createHash } from "node:crypto";
import { readFile, stat } from "node:fs/promises";
import { extractLegacyItems } from "./inspect/cells.js";
import { LegacyImportError } from "./inspect/errors.js";
import { inspectOoxmlPackage } from "./inspect/ooxml.js";
import {
  assertProfileMatchesInspection,
  loadPinnedProfile
} from "./inspect/profile.js";
import type { LegacyImportDto } from "./inspect/types.js";
import { inspectZipPackage, ZIP_LIMITS } from "./inspect/zip.js";

export { LegacyImportError } from "./inspect/errors.js";
export type {
  LegacyCellDto,
  LegacyCellValue,
  LegacyImportDto,
  LegacyItemDto,
  LegacyPackageDto
} from "./inspect/types.js";

export async function importLegacyWorkbook(
  source: string | URL,
  options: { readonly manifestRoot?: URL } = {}
): Promise<LegacyImportDto> {
  const bytes = await readSource(source);
  const sourceSha256 = createHash("sha256").update(bytes).digest("hex");
  const profile = await loadPinnedProfile(
    sourceSha256,
    options.manifestRoot
  );
  try {
    const inspected = await inspectZipPackage(bytes);
    const ooxml = await inspectOoxmlPackage(inspected);
    assertProfileMatchesInspection(profile, ooxml);
    const items = await extractLegacyItems(
      inspected.archive,
      ooxml.resolvedSheets,
      profile
    );
    return {
      schemaVersion: "legacy-import-v1",
      profileId: profile.profileId,
      profileSlug: profile.slug,
      sourceSha256,
      capacity: profile.capacity.rows,
      items,
      baselineInventory: profile.baselineInventory,
      inheritedWarnings: profile.inheritedWarnings,
      package: inspected.package
    };
  } catch (error) {
    if (error instanceof LegacyImportError) {
      throw error;
    }
    throw new LegacyImportError("CORRUPT_OOXML");
  }
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
