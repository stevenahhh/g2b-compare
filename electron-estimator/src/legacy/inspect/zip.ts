import { createHash } from "node:crypto";
import JSZip from "jszip";
import { scanCentralDirectory } from "./central-directory.js";
import { LegacyImportError } from "./errors.js";
import type { LegacyPackageDto } from "./types.js";

export { ZIP_LIMITS } from "./central-directory.js";

export type InspectedZipPackage = {
  readonly archive: JSZip;
  readonly package: LegacyPackageDto;
  readonly names: readonly string[];
};

export async function inspectZipPackage(
  bytes: Uint8Array
): Promise<InspectedZipPackage> {
  const members = scanCentralDirectory(bytes);
  let archive: JSZip;
  try {
    archive = await JSZip.loadAsync(bytes, {
      checkCRC32: true,
      createFolders: false
    });
  } catch {
    throw new LegacyImportError("CORRUPT_OOXML");
  }
  const names = members.map((member) => member.name).toSorted();
  if (JSON.stringify(Object.keys(archive.files).toSorted()) !== JSON.stringify(names)) {
    throw new LegacyImportError("CORRUPT_OOXML");
  }
  const hashes: [string, string][] = [];
  for (const name of names) {
    const entry = archive.files[name];
    if (entry === undefined) {
      throw new LegacyImportError("CORRUPT_OOXML");
    }
    const content = await entry.async("uint8array");
    hashes.push([
      name,
      createHash("sha256").update(content).digest("hex")
    ]);
  }
  return {
    archive,
    names,
    package: {
      memberCount: names.length,
      uncompressedBytes: members.reduce(
        (total, member) => total + member.uncompressedBytes,
        0
      ),
      memberSha256: Object.fromEntries(hashes),
      specialParts: countSpecialParts(names)
    }
  };
}

function countSpecialParts(names: readonly string[]): LegacyPackageDto["specialParts"] {
  return {
    drawings: names.filter((name) => name.startsWith("xl/drawings/")).length,
    media: names.filter((name) => name.startsWith("xl/media/")).length,
    comments: names.filter((name) => name.startsWith("xl/comments")).length,
    vml: names.filter((name) => name.endsWith(".vml")).length,
    activeX: names.filter((name) => name.startsWith("xl/activeX/")).length,
    printerSettings: names.filter((name) =>
      name.startsWith("xl/printerSettings/")
    ).length,
    externalLinks: names.filter(isExternalLinkPart).length
  };
}

function isExternalLinkPart(name: string): boolean {
  const prefix = "xl/externalLinks/externalLink";
  const suffix = ".xml";
  if (!name.startsWith(prefix) || !name.endsWith(suffix)) {
    return false;
  }
  const number = name.slice(prefix.length, -suffix.length);
  return number.length > 0 && [...number].every((character) =>
    character >= "0" && character <= "9"
  );
}
