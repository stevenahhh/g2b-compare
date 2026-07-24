import type { LegacyProfileManifest } from "../inspect/profile.js";
import type {
  OoxmlInspection
} from "../inspect/ooxml.js";
import type { InspectedZipPackage } from "../inspect/zip.js";

export type WarningCounts = {
  readonly cachedFormulaError: readonly [number, number];
  readonly formulaReferenceError: readonly [number, number];
  readonly externalLink: readonly [number, number];
  readonly problemDefinedName: readonly [number, number];
};

export function packageChanges(
  original: InspectedZipPackage,
  output: InspectedZipPackage
): readonly string[] {
  const names = new Set([...original.names, ...output.names]);
  return [...names]
    .filter((name) => !name.endsWith("/"))
    .filter(
      (name) =>
        original.package.memberSha256[name] !==
        output.package.memberSha256[name]
    )
    .toSorted();
}

export function vbaChanged(
  original: InspectedZipPackage,
  output: InspectedZipPackage
): boolean {
  const originalVba = original.names
    .filter((name) => name.toLocaleLowerCase("en-US").includes("/vba"))
    .map((name) => `${name}=${original.package.memberSha256[name]}`)
    .toSorted();
  const outputVba = output.names
    .filter((name) => name.toLocaleLowerCase("en-US").includes("/vba"))
    .map((name) => `${name}=${output.package.memberSha256[name]}`)
    .toSorted();
  return !same(originalVba, outputVba);
}

export function formulaInventoryChanged(
  manifest: LegacyProfileManifest,
  output: OoxmlInspection
): boolean {
  return (
    manifest.baselineInventory.formulaErrors.formulaTextCount !==
      output.baselineInventory.formulaErrors.formulaTextCount ||
    manifest.baselineInventory.formulaErrors.formulaTextFingerprint !==
      output.baselineInventory.formulaErrors.formulaTextFingerprint
  );
}

export function cacheInventoryChanged(
  manifest: LegacyProfileManifest,
  output: OoxmlInspection
): boolean {
  return (
    manifest.baselineInventory.formulaErrors.cachedErrorCount !==
      output.baselineInventory.formulaErrors.cachedErrorCount ||
    manifest.baselineInventory.formulaErrors.cachedErrorFingerprint !==
      output.baselineInventory.formulaErrors.cachedErrorFingerprint
  );
}

export function sheetStructureChanged(
  manifest: LegacyProfileManifest,
  output: OoxmlInspection
): boolean {
  const structural = (sheet: OoxmlInspection["sheetMap"][number]) => ({
    name: sheet.name,
    part: sheet.part,
    dimension: sheet.dimension,
    mergedRanges: sheet.mergedRanges,
    formulaCells: sheet.formulaCells
  });
  return !same(
    manifest.sheetMap.map(structural),
    output.sheetMap.map(structural)
  );
}

export function externalLinksChanged(
  manifest: LegacyProfileManifest,
  output: OoxmlInspection
): boolean {
  const baseline = manifest.baselineInventory;
  const inspected = output.baselineInventory;
  return (
    !same(baseline.externalLinks, inspected.externalLinks) ||
    baseline.definedNames.externalCount !== inspected.definedNames.externalCount ||
    baseline.definedNames.externalFingerprint !==
      inspected.definedNames.externalFingerprint ||
    manifest.sheetMap.some(
      (sheet, index) =>
        sheet.externalFormulaReferences !==
        output.sheetMap[index]?.externalFormulaReferences
    )
  );
}

export function definedNamesChanged(
  manifest: LegacyProfileManifest,
  output: OoxmlInspection
): boolean {
  return !same(
    manifest.baselineInventory.definedNames,
    output.baselineInventory.definedNames
  );
}

export function warningCounts(
  manifest: LegacyProfileManifest,
  output: OoxmlInspection
): WarningCounts {
  const baseline = manifest.baselineInventory;
  const inspected = output.baselineInventory;
  return {
    cachedFormulaError: [
      baseline.formulaErrors.cachedErrorCount,
      inspected.formulaErrors.cachedErrorCount
    ],
    formulaReferenceError: [
      baseline.formulaErrors.formulaTextCount,
      inspected.formulaErrors.formulaTextCount
    ],
    externalLink: [baseline.externalLinks.count, inspected.externalLinks.count],
    problemDefinedName: [
      baseline.definedNames.problemCount,
      inspected.definedNames.problemCount
    ]
  };
}

function same(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}
