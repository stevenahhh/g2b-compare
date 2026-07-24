import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { resolve, sep } from "node:path";
import JSZip from "jszip";

const PROJECT_ROOT = resolve(import.meta.dirname, "..");
const DATASET_ROOT = resolve(PROJECT_ROOT, "..", "dataset");
const ERROR_PATTERN = /#(?:REF!|VALUE!|NAME\?|DIV\/0!)/gu;

export async function verifyWorkbook(
  inputPath,
  options = {}
) {
  const path = resolve(inputPath);
  if (
    options.rejectSourceDataset === true &&
    (path === DATASET_ROOT || path.startsWith(`${DATASET_ROOT}${sep}`))
  ) {
    throw new TypeError("QA_SOURCE_PATH_FORBIDDEN");
  }
  const bytes = await readFile(path);
  const archive = await JSZip.loadAsync(bytes);
  const workbookXml = await requiredText(archive, "xl/workbook.xml");
  await requiredText(archive, "[Content_Types].xml");
  const sheetNames = [...workbookXml.matchAll(
    /<sheet\b[^>]*\bname="([^"]+)"/gu
  )].map((match) => decodeXml(match[1] ?? ""));
  if (sheetNames.length === 0) {
    throw new TypeError("QA_WORKBOOK_HAS_NO_SHEETS");
  }
  const worksheetParts = Object.keys(archive.files)
    .filter((name) => /^xl\/worksheets\/sheet\d+[.]xml$/u.test(name))
    .toSorted();
  const formulaErrors = [];
  let formulaCount = 0;
  for (const part of worksheetParts) {
    const xml = await requiredText(archive, part);
    formulaCount += [...xml.matchAll(/<f(?:\s[^>]*)?>/gu)].length;
    for (const match of xml.matchAll(ERROR_PATTERN)) {
      formulaErrors.push({ part, value: match[0], offset: match.index });
    }
  }
  return Object.freeze({
    status: "pass",
    path,
    sha256: sha256(bytes),
    byteLength: bytes.length,
    sheetNames,
    worksheetPartCount: worksheetParts.length,
    formulaCount,
    formulaErrors
  });
}

async function requiredText(archive, part) {
  const entry = archive.file(part);
  if (entry === null) {
    throw new TypeError(`QA_WORKBOOK_PART_MISSING:${part}`);
  }
  return entry.async("string");
}

function decodeXml(value) {
  return value
    .replaceAll("&quot;", "\"")
    .replaceAll("&apos;", "'")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&amp;", "&");
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

if (
  process.argv[1] !== undefined &&
  resolve(process.argv[1]) === resolve(import.meta.filename)
) {
  const input = process.argv[2];
  if (input === undefined) {
    throw new TypeError("Usage: node scripts/verify-workbook.mjs <xlsx>");
  }
  console.log(JSON.stringify(await verifyWorkbook(input), null, 2));
}
