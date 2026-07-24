import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { z } from "zod";
import { LegacyImportError } from "../inspect/errors.js";
import {
  LegacyProfileManifestSchema,
  type LegacyProfileManifest
} from "../inspect/profile.js";

const PROFILE_DEFINITIONS = [
  {
    sourceSha256:
      "445012e259ab5318a1d52468cce93ee28a55a8bcb467876f40a47a939e4668db",
    manifest: "gwangyang-direct-2025.json",
    manifestSha256:
      "ea17079a74f076722a100d6ee5d3aad6e8d6cb842cc2fffadb603649401eda1e"
  },
  {
    sourceSha256:
      "2220cd9936ebdf908d64c0571a4c8de83973eaa89c6778a64afec07de7c5e701",
    manifest: "suncheon-procurement-2025.json",
    manifestSha256:
      "3dc0c6105c7ae70e810206d6d049c6dda92df6ba2fe6956d57b0ff4e2319f135"
  },
  {
    sourceSha256:
      "8a55700bdaf62a00c208c7286531fd56ca321571f73f7620505a823ef5d4d0f1",
    manifest: "gwangyang-procurement-final-2025.json",
    manifestSha256:
      "575f636fcbd9107d0049cb4445069b7d57ff77d61f767d5d969de849312d0df4"
  }
] as const;

const OwnershipSchema = z
  .strictObject({
    MODEL_INPUT: z.array(z.string()).readonly(),
    VALID_TEMPLATE_FORMULA: z.array(z.string()).readonly(),
    CANONICAL_OVERRIDE_FORMULA: z.array(z.string()).readonly(),
    GENERATED_DISPLAY: z.array(z.string()).readonly(),
    LEGACY_DORMANT: z.array(z.string()).readonly(),
    UNUSED_SLOT: z.array(z.string()).readonly(),
    TEMPLATE_STATIC: z.array(z.string()).readonly()
  })
  .readonly();

const PatchFieldsSchema = z
  .object({
    ownership: OwnershipSchema,
    formulaCacheCells: z.array(z.string()).readonly(),
    packageDriftAllowlist: z.array(z.string()).readonly()
  })
  .readonly();

const PatchProfileSchema =
  LegacyProfileManifestSchema.and(PatchFieldsSchema);

export type PatchProfile = LegacyProfileManifest &
  z.output<typeof PatchFieldsSchema>;

const MANIFEST_ROOT = new URL(
  "../../../resources/manifests/legacy/",
  import.meta.url
);

const CALC_DRIFT_ALLOWLIST = [
  "[Content_Types].xml#calcChain-override",
  "xl/_rels/workbook.xml.rels#calcChain-relationship",
  "xl/calcChain.xml",
  "xl/workbook.xml#calcPr"
] as const;

export async function loadPatchProfile(
  sourceSha256: string,
  manifestRoot: URL | undefined = MANIFEST_ROOT
): Promise<PatchProfile> {
  const definition = PROFILE_DEFINITIONS.find(
    (candidate) => candidate.sourceSha256 === sourceSha256
  );
  if (definition === undefined) {
    throw new LegacyImportError("UNSUPPORTED_WORKBOOK");
  }
  try {
    const raw: unknown = JSON.parse(
      await readFile(
        new URL(definition.manifest, manifestRoot ?? MANIFEST_ROOT),
        "utf8"
      )
    );
    const digest = createHash("sha256")
      .update(JSON.stringify(canonical(raw)))
      .digest("hex");
    if (digest !== definition.manifestSha256) {
      throw new LegacyImportError("STALE_PROFILE");
    }
    const profile = PatchProfileSchema.parse(raw);
    if (
      profile.source.sha256 !== sourceSha256 ||
      profile.ownership.CANONICAL_OVERRIDE_FORMULA.length !== 0 ||
      JSON.stringify(profile.packageDriftAllowlist) !==
        JSON.stringify(CALC_DRIFT_ALLOWLIST)
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

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(canonical);
  }
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .toSorted(([left], [right]) => left.localeCompare(right))
        .map(([key, child]) => [key, canonical(child)])
    );
  }
  return value;
}
