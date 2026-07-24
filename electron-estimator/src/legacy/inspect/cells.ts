import type JSZip from "jszip";
import { wantedCells } from "./cell-address.js";
import {
  parseWorksheetCells,
  readSharedStrings
} from "./cell-values.js";
import { buildItems } from "./items.js";
import type { ResolvedSheet } from "./ooxml-types.js";
import type { LegacyProfileManifest } from "./profile.js";
import type { LegacyCellDto, LegacyItemDto } from "./types.js";
import { zipText } from "./xml.js";

export async function extractLegacyItems(
  archive: JSZip,
  sheets: readonly ResolvedSheet[],
  profile: LegacyProfileManifest
): Promise<readonly LegacyItemDto[]> {
  const sharedStrings = await readSharedStrings(archive);
  const wanted = wantedCells(profile.appOwnedCells);
  const cells: LegacyCellDto[] = [];
  for (const sheet of sheets) {
    const points = wanted.get(sheet.name);
    if (points === undefined) {
      continue;
    }
    const parsed = parseWorksheetCells({
      wanted: new Set(points.map((point) => point.address)),
      sharedStrings,
      xml: await zipText(archive, sheet.part)
    });
    for (const point of points) {
      cells.push({
        sheet: sheet.name,
        address: point.address,
        value: parsed.get(point.address) ?? { kind: "blank" }
      });
    }
  }
  return buildItems(profile, cells);
}
