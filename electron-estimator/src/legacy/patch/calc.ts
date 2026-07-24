import type JSZip from "jszip";
import { LegacyImportError } from "../inspect/errors.js";
import { zipText } from "../inspect/xml.js";
import {
  applyXmlReplacements,
  nodeAttribute,
  rewriteNodeTag,
  scanXmlNodes,
  type XmlReplacement
} from "./xml-nodes.js";

const PARTS = {
  contentTypes: "[Content_Types].xml",
  relationships: "xl/_rels/workbook.xml.rels",
  workbook: "xl/workbook.xml",
  calcChain: "xl/calcChain.xml"
} as const;

type CalcInvalidationInput = {
  readonly archive: JSZip;
  readonly packageDriftAllowlist: readonly string[];
};

export async function invalidateCalculationMetadata(
  input: CalcInvalidationInput
): Promise<readonly string[]> {
  assertDeclaredAllowlist(input.packageDriftAllowlist);
  const changed = new Set<string>();
  await removeSelectedNodes({
    archive: input.archive,
    part: PARTS.contentTypes,
    local: "Override",
    matches: (node) =>
      nodeAttribute(node, "PartName") === "/xl/calcChain.xml",
    changed
  });
  await removeSelectedNodes({
    archive: input.archive,
    part: PARTS.relationships,
    local: "Relationship",
    matches: (node) =>
      nodeAttribute(node, "Type")?.endsWith("/calcChain") === true,
    changed
  });
  await setFullCalculation(input.archive, changed);
  if (input.archive.files[PARTS.calcChain] !== undefined) {
    input.archive.remove(PARTS.calcChain);
    changed.add(PARTS.calcChain);
  }
  return [...changed].toSorted();
}

type NodeRemovalInput = {
  readonly archive: JSZip;
  readonly part: string;
  readonly local: string;
  readonly matches: (
    node: ReturnType<typeof scanXmlNodes>[number]
  ) => boolean;
  readonly changed: Set<string>;
};

async function removeSelectedNodes(input: NodeRemovalInput): Promise<void> {
  const xml = await zipText(input.archive, input.part);
  const matches = scanXmlNodes(xml).filter(
    (node) => node.local === input.local && input.matches(node)
  );
  if (matches.length !== 1) {
    throw new LegacyImportError("STALE_PROFILE");
  }
  const updated = applyXmlReplacements(
    xml,
    matches.map((node) => ({
      start: node.start,
      end: node.end,
      value: ""
    }))
  );
  replaceArchivePart(input.archive, input.part, updated);
  input.changed.add(input.part);
}

async function setFullCalculation(
  archive: JSZip,
  changed: Set<string>
): Promise<void> {
  const xml = await zipText(archive, PARTS.workbook);
  const nodes = scanXmlNodes(xml);
  const calcProperties = nodes.filter((node) => node.local === "calcPr");
  if (calcProperties.length !== 1) {
    throw new LegacyImportError("STALE_PROFILE");
  }
  const node = calcProperties[0];
  if (node === undefined) {
    throw new LegacyImportError("STALE_PROFILE");
  }
  const overrides = new Map<string, string>([
    ["calcMode", "auto"],
    ["fullCalcOnLoad", "1"],
    ["forceFullCalc", "1"],
    ["calcOnSave", "1"]
  ]);
  const replacement: XmlReplacement = {
    start: node.start,
    end: node.end,
    value: rewriteNodeTag(node, overrides, true)
  };
  const updated = applyXmlReplacements(xml, [replacement]);
  replaceArchivePart(archive, PARTS.workbook, updated);
  changed.add(PARTS.workbook);
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

function assertDeclaredAllowlist(allowlist: readonly string[]): void {
  const expected = [
    "[Content_Types].xml#calcChain-override",
    "xl/_rels/workbook.xml.rels#calcChain-relationship",
    "xl/calcChain.xml",
    "xl/workbook.xml#calcPr"
  ];
  if (JSON.stringify(allowlist) !== JSON.stringify(expected)) {
    throw new LegacyImportError("STALE_PROFILE");
  }
}
