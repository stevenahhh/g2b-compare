import { readFile } from "node:fs/promises";
import { z } from "zod";
import { LegacyImportError } from "./errors.js";
import type { OoxmlInspection } from "./ooxml.js";

const Sha256Schema = z.string().regex(/^[0-9a-f]{64}$/u);
const FingerprintSchema = z.object({
  count: z.number().int().nonnegative(),
  fingerprint: Sha256Schema
}).readonly();
const SheetSchema = z.object({
  name: z.string().min(1),
  part: z.string().min(1),
  dimension: z.string().min(1),
  formulaCells: z.number().int().nonnegative(),
  mergedRanges: z.number().int().nonnegative(),
  externalFormulaReferences: z.number().int().nonnegative()
}).readonly();
const BaselineInventorySchema = z.object({
  externalLinks: FingerprintSchema,
  definedNames: z.object({
    count: z.number().int().nonnegative(),
    fingerprint: Sha256Schema,
    problemCount: z.number().int().nonnegative(),
    problemFingerprint: Sha256Schema,
    externalCount: z.number().int().nonnegative(),
    externalFingerprint: Sha256Schema
  }).readonly(),
  formulaErrors: z.object({
    formulaTextCount: z.number().int().nonnegative(),
    formulaTextFingerprint: Sha256Schema,
    cachedErrorCount: z.number().int().nonnegative(),
    cachedErrorFingerprint: Sha256Schema
  }).readonly(),
  calcChain: z.object({
    present: z.boolean(),
    entryCount: z.number().int().nonnegative(),
    fingerprint: Sha256Schema
  }).readonly()
}).readonly();
const SourceSchema = z.object({
  sha256: Sha256Schema,
  packageParts: FingerprintSchema
}).readonly();
const SharedFields = {
  schemaVersion: z.literal("legacy-workbook-profile-v1"),
  slug: z.string().min(1),
  source: SourceSchema,
  sheetMap: z.array(SheetSchema).min(1).readonly(),
  appOwnedCells: z.array(z.string().min(1)).min(1).readonly(),
  baselineInventory: BaselineInventorySchema,
  inheritedWarnings: z.object({
    disposition: z.string().min(1),
    originalFormulaCells: z.array(z.string()).readonly()
  }).readonly()
} as const;
const DirectProfileSchema = z.object({
  ...SharedFields,
  profileId: z.literal("A"),
  capacity: z.object({ rows: z.literal(16) }).readonly(),
  rowMap: z.object({
    itemRows: z.array(z.number().int().positive()).length(16).readonly()
  }).readonly()
}).readonly();
const ProcurementProfileSchema = (id: "B" | "C", rows: 9 | 24) =>
  z.object({
    ...SharedFields,
    profileId: z.literal(id),
    capacity: z.object({ rows: z.literal(rows) }).readonly(),
    rowMap: z.object({
      quantityRows: z.string().min(1),
      priceRows: z.string().min(1)
    }).readonly()
  }).readonly();

export const LegacyProfileManifestSchema = z.discriminatedUnion("profileId", [
  DirectProfileSchema,
  ProcurementProfileSchema("B", 9),
  ProcurementProfileSchema("C", 24)
]);

export type LegacyProfileManifest =
  z.output<typeof LegacyProfileManifestSchema>;

const PINNED_PROFILES = [
  {
    profileId: "A",
    slug: "gwangyang-direct-2025",
    manifest: "gwangyang-direct-2025.json",
    sourceSha256:
      "445012e259ab5318a1d52468cce93ee28a55a8bcb467876f40a47a939e4668db",
    capacity: 16,
    members: 46,
    externalLinks: 0
  },
  {
    profileId: "B",
    slug: "suncheon-procurement-2025",
    manifest: "suncheon-procurement-2025.json",
    sourceSha256:
      "2220cd9936ebdf908d64c0571a4c8de83973eaa89c6778a64afec07de7c5e701",
    capacity: 9,
    members: 850,
    externalLinks: 319
  },
  {
    profileId: "C",
    slug: "gwangyang-procurement-final-2025",
    manifest: "gwangyang-procurement-final-2025.json",
    sourceSha256:
      "8a55700bdaf62a00c208c7286531fd56ca321571f73f7620505a823ef5d4d0f1",
    capacity: 24,
    members: 601,
    externalLinks: 253
  }
] as const;
const MANIFEST_ROOT = new URL(
  "../../../resources/manifests/legacy/",
  import.meta.url
);

export async function loadPinnedProfile(
  sourceSha256: string,
  manifestRoot: URL | undefined = MANIFEST_ROOT
): Promise<LegacyProfileManifest> {
  const pin = PINNED_PROFILES.find(
    (candidate) => candidate.sourceSha256 === sourceSha256
  );
  if (pin === undefined) {
    throw new LegacyImportError("UNSUPPORTED_WORKBOOK");
  }
  try {
    const input: unknown = JSON.parse(
      await readFile(new URL(pin.manifest, manifestRoot ?? MANIFEST_ROOT), "utf8")
    );
    const profile = LegacyProfileManifestSchema.parse(input);
    if (
      profile.profileId !== pin.profileId ||
      profile.slug !== pin.slug ||
      profile.source.sha256 !== pin.sourceSha256 ||
      profile.capacity.rows !== pin.capacity ||
      profile.source.packageParts.count !== pin.members ||
      profile.baselineInventory.externalLinks.count !== pin.externalLinks
    ) {
      throw new LegacyImportError("STALE_PROFILE");
    }
    return profile;
  } catch (error) {
    if (error instanceof LegacyImportError) {
      throw error;
    }
    throw new LegacyImportError("STALE_PROFILE");
  }
}

export function assertProfileMatchesInspection(
  profile: LegacyProfileManifest,
  inspection: OoxmlInspection
): void {
  if (
    JSON.stringify(profile.source.packageParts) !==
      JSON.stringify(inspection.packageParts) ||
    JSON.stringify(profile.sheetMap) !== JSON.stringify(inspection.sheetMap) ||
    JSON.stringify(profile.baselineInventory) !==
      JSON.stringify(inspection.baselineInventory)
  ) {
    throw new LegacyImportError("STALE_PROFILE");
  }
}
