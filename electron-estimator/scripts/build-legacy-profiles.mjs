import { createHash } from "node:crypto";
import { readFile, stat } from "node:fs/promises";
import { basename, dirname, isAbsolute, posix, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ExcelJS from "exceljs";
import JSZip from "jszip";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const manifestDirectory = resolve(root, "resources/manifests/legacy");
const profileDefinitions = [
  {
    manifest: "gwangyang-direct-2025.json", id: "A", capacity: 16, totalWon: 39149530,
    filename: "250725-전남 광양시 아트케이션 관광스테이 확충사업 CCTV 설비 내역서.xlsx",
    sha256: "445012e259ab5318a1d52468cce93ee28a55a8bcb467876f40a47a939e4668db",
    manifestSha256: "ea17079a74f076722a100d6ee5d3aad6e8d6cb842cc2fffadb603649401eda1e",
    formulaFingerprint: "12c6350721319f61a5d3415f9c549c33458a09ec3c2021c25b846518687fb894"
  },
  {
    manifest: "suncheon-procurement-2025.json", id: "B", capacity: 9, totalWon: 20284000,
    filename: "순천 향교 CCTV 구매 설치 - 내역서(관급)(0706수정).xlsx",
    sha256: "2220cd9936ebdf908d64c0571a4c8de83973eaa89c6778a64afec07de7c5e701",
    manifestSha256: "3dc0c6105c7ae70e810206d6d049c6dda92df6ba2fe6956d57b0ff4e2319f135",
    formulaFingerprint: "fbc75ff96ab44d24867b16f5d6fa1c09f5964b1539b9d5c8cb5c8b2e501fe568"
  },
  {
    manifest: "gwangyang-procurement-final-2025.json", id: "C", capacity: 24, totalWon: 65854000,
    filename: "전남 광양시 아트케이션 관광스테이 확충사업 CCTV 설비 - 내역서(관급)(최종).xlsx",
    sha256: "8a55700bdaf62a00c208c7286531fd56ca321571f73f7620505a823ef5d4d0f1",
    manifestSha256: "575f636fcbd9107d0049cb4445069b7d57ff77d61f767d5d969de849312d0df4",
    formulaFingerprint: "1dd24082c48e03ac8b624df0be4fd26f65ec10afa83da0c2ee389667bd511990"
  }
];
const ownershipKinds = [
  "MODEL_INPUT", "VALID_TEMPLATE_FORMULA", "CANONICAL_OVERRIDE_FORMULA",
  "GENERATED_DISPLAY", "LEGACY_DORMANT", "UNUSED_SLOT", "TEMPLATE_STATIC"
];
const requiredFields = [
  "schemaVersion", "profileId", "slug", "family", "source", "sheetMap", "capacity",
  "rowMap", "ownershipBoundary", "ownership", "appOwnedCells", "activeFormula",
  "formulaCacheCells", "packageDriftAllowlist", "totalOracle", "baselineInventory",
  "inheritedWarnings"
];
const cWarningCells = [
  "관급내역서!U13=단가조사!F18", "관급내역서!U14=단가조사!F19",
  "관급내역서!U15=단가조사!F20", "관급내역서!U16=단가조사!F21",
  "관급내역서!U17=단가조사!F22"
];
const errorTokens = ["#REF!", "#NAME?", "#VALUE!", "#DIV/0!", "#N/A", "#NUM!", "#NULL!"];

const sha256 = (value) => createHash("sha256").update(value).digest("hex");
const fingerprint = (records) => sha256(records.join("\n"));

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])]));
  }
  return value;
}

function decodeXml(value) {
  return value
    .replace(/&#(x[0-9a-f]+|\d+);/gi, (_, code) =>
      String.fromCodePoint(code[0].toLowerCase() === "x" ? Number.parseInt(code.slice(1), 16) : Number(code)))
    .replaceAll("&quot;", "\"").replaceAll("&apos;", "'").replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">").replaceAll("&amp;", "&");
}

function attributes(fragment) {
  return Object.fromEntries(
    [...fragment.matchAll(/([\w:]+)="([^"]*)"/g)].map((match) => [match[1], decodeXml(match[2])])
  );
}

function requireMatch(value, pattern, code) {
  const match = value.match(pattern);
  if (!match) throw new Error(code);
  return match;
}

async function zipText(zip, part) {
  const entry = zip.file(part);
  if (!entry) throw new Error(`LEGACY_PACKAGE_PART_MISSING ${part}`);
  return entry.async("text");
}

function worksheetInventory(sheet, xml) {
  const formulaErrors = [];
  const cachedErrors = [];
  const dimension = decodeXml(
    requireMatch(xml, /<dimension\b[^>]*\bref="([^"]+)"/, "LEGACY_DIMENSION_MISSING")[1]
  );
  const formulaCells = [...xml.matchAll(/<f(?:\s|\/|>)/g)].length;
  const mergedRanges = [...xml.matchAll(/<mergeCell\b/g)].length;
  const formulas = [...xml.matchAll(/<f(?:\s[^>]*)?>([\s\S]*?)<\/f>/g)].map((item) => decodeXml(item[1]));
  for (const match of xml.matchAll(/<c\s+([^>]*?)(?:\/>|>([\s\S]*?)<\/c>)/g)) {
    const cell = attributes(match[1]);
    const body = match[2] ?? "";
    const formula = body.match(/<f(?:\s[^>]*)?>([\s\S]*?)<\/f>/);
    if (formula && errorTokens.some((token) => formula[1].includes(token))) {
      formulaErrors.push(`${sheet.name}!${cell.r}=${decodeXml(formula[1])}`);
    }
    if (cell.t === "e") {
      const cached = body.match(/<v>([\s\S]*?)<\/v>/);
      cachedErrors.push(`${sheet.name}!${cell.r}=${decodeXml(cached?.[1] ?? "")}`);
    }
  }
  return {
    sheet: {
      ...sheet, dimension, formulaCells, mergedRanges,
      externalFormulaReferences: formulas.filter((formula) => formula.includes("[") && formula.includes("]")).length
    },
    formulaErrors,
    cachedErrors
  };
}

async function inspectPackage(zip) {
  const parts = Object.keys(zip.files).sort();
  const workbookXml = await zipText(zip, "xl/workbook.xml");
  const relationshipsXml = await zipText(zip, "xl/_rels/workbook.xml.rels");
  const relationships = Object.fromEntries(
    [...relationshipsXml.matchAll(/<Relationship\b([^>]*)\/?>/g)].map((match) => {
      const item = attributes(match[1]);
      return [item.Id, item.Target];
    })
  );
  const sheetMap = [];
  const formulaErrors = [];
  const cachedErrors = [];
  for (const match of workbookXml.matchAll(/<sheet\b([^>]*)\/?>/g)) {
    const sheet = attributes(match[1]);
    const target = relationships[sheet["r:id"]];
    if (!target) throw new Error(`LEGACY_SHEET_RELATION_MISSING ${sheet.name}`);
    const part = target.startsWith("/") ? target.slice(1) : posix.normalize(posix.join("xl", target));
    const item = worksheetInventory({ name: sheet.name, part }, await zipText(zip, part));
    sheetMap.push(item.sheet);
    formulaErrors.push(...item.formulaErrors);
    cachedErrors.push(...item.cachedErrors);
  }
  const definedNames = [...workbookXml.matchAll(
    /<definedName\b([^>]*?)(?:\/>|>([\s\S]*?)<\/definedName>)/g
  )].map((match) => {
    const item = attributes(match[1]);
    return [item.name ?? "", item.localSheetId ?? "", item.hidden ?? "", decodeXml(match[2] ?? "")].join("|");
  });
  const problemNames = definedNames.filter((item) => errorTokens.some((token) => item.includes(token)));
  const externalNames = definedNames.filter((item) => item.includes("[") && item.includes("]"));
  const externalLinks = parts.filter((part) => /^xl\/externalLinks\/externalLink\d+\.xml$/i.test(part));
  const calcChain = [];
  if (zip.file("xl/calcChain.xml")) {
    const calcXml = await zipText(zip, "xl/calcChain.xml");
    for (const match of calcXml.matchAll(/<c\b([^>]*)\/?>/g)) {
      const item = attributes(match[1]);
      calcChain.push([item.i ?? "", item.r ?? "", item.l ?? "", item.s ?? ""].join("|"));
    }
  }
  return {
    packageParts: { count: parts.length, fingerprint: fingerprint(parts) },
    sheetMap,
    baselineInventory: {
      externalLinks: { count: externalLinks.length, fingerprint: fingerprint(externalLinks) },
      definedNames: {
        count: definedNames.length, fingerprint: fingerprint(definedNames),
        problemCount: problemNames.length, problemFingerprint: fingerprint(problemNames),
        externalCount: externalNames.length, externalFingerprint: fingerprint(externalNames)
      },
      formulaErrors: {
        formulaTextCount: formulaErrors.length, formulaTextFingerprint: fingerprint(formulaErrors),
        cachedErrorCount: cachedErrors.length, cachedErrorFingerprint: fingerprint(cachedErrors)
      },
      calcChain: {
        present: calcChain.length > 0, entryCount: calcChain.length, fingerprint: fingerprint(calcChain)
      }
    }
  };
}

function formulaRange(reference) {
  const separator = reference.lastIndexOf("!");
  const sheet = reference.slice(0, separator);
  const [start, end] = reference.slice(separator + 1).split(":");
  const point = (cell) => {
    const match = requireMatch(cell, /^([A-Z]+)(\d+)$/, `LEGACY_ACTIVE_FORMULA_RANGE_INVALID ${reference}`);
    const column = [...match[1]].reduce((value, char) => value * 26 + char.charCodeAt(0) - 64, 0);
    return { column, row: Number(match[2]) };
  };
  return { sheet, start: point(start), end: point(end ?? start) };
}

async function activeFormulaInventory(bytes, manifest) {
  const workbook = new ExcelJS.Workbook();
  await workbook.xlsx.load(bytes);
  const combined = [];
  const ranges = [];
  for (const expected of manifest.activeFormula.ranges) {
    const range = formulaRange(expected.range);
    const sheet = workbook.getWorksheet(range.sheet);
    if (!sheet) throw new Error(`LEGACY_ACTIVE_FORMULA_SHEET_MISSING ${expected.range}`);
    const records = [];
    const combinedRecords = [];
    for (let row = range.start.row; row <= range.end.row; row += 1) {
      for (let column = range.start.column; column <= range.end.column; column += 1) {
        const cell = sheet.getCell(row, column);
        if (typeof cell.formula === "string") {
          records.push(`${cell.address}==${cell.formula}`);
          combinedRecords.push(`${sheet.name}!${cell.address}==${cell.formula}`);
        }
      }
    }
    combined.push(...combinedRecords);
    ranges.push({ range: expected.range, formulaCells: records.length, fingerprint: fingerprint(records) });
  }
  return { cellCount: combined.length, ranges, combinedFingerprint: fingerprint(combined) };
}

function assertSame(actual, expected, code) {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`${code} actual=${JSON.stringify(actual)} expected=${JSON.stringify(expected)}`);
  }
}

function validateManifest(manifest, definition) {
  const fail = (field) => { throw new Error(`LEGACY_PROFILE_SEMANTIC_MISMATCH ${definition.id} ${field}`); };
  if (!requiredFields.every((field) => Object.hasOwn(manifest, field))) fail("requiredFields");
  if (
    manifest.schemaVersion !== "legacy-workbook-profile-v1" ||
    manifest.profileId !== definition.id ||
    typeof manifest.slug !== "string" ||
    typeof manifest.family !== "string"
  ) fail("identity");
  if (manifest.capacity?.rows !== definition.capacity || !Object.keys(manifest.rowMap ?? {}).length) fail("capacity");
  if (
    !ownershipKinds.every((kind) => Array.isArray(manifest.ownership?.[kind])) ||
    Object.keys(manifest.ownership ?? {}).length !== ownershipKinds.length ||
    !manifest.ownership.MODEL_INPUT.length ||
    !manifest.ownership.VALID_TEMPLATE_FORMULA.length ||
    (definition.id !== "C" && manifest.ownership.CANONICAL_OVERRIDE_FORMULA.length) ||
    !manifest.appOwnedCells?.length
  ) fail("ownership");
  if (!manifest.formulaCacheCells?.length || typeof manifest.inheritedWarnings?.disposition !== "string") {
    fail("warningDisposition");
  }
  if (
    manifest.activeFormula?.algorithm !== "research-active-formula-v1" ||
    manifest.activeFormula?.recordFormat !== "sheet!cell=formula joined with LF in workbook order" ||
    manifest.activeFormula?.combinedFingerprint !== definition.formulaFingerprint ||
    !Number.isInteger(manifest.activeFormula?.cellCount) ||
    !manifest.activeFormula?.ranges?.length
  ) fail("activeFormula");
  const warnings = manifest.inheritedWarnings.originalFormulaCells;
  if (!Array.isArray(warnings) || (definition.id !== "C" && warnings.length)) fail("warningDisposition");
  if (
    definition.id === "C" &&
    (
      JSON.stringify(warnings) !== JSON.stringify(cWarningCells) ||
      manifest.ownership.CANONICAL_OVERRIDE_FORMULA.length ||
      !manifest.ownership.LEGACY_DORMANT.includes("관급내역서!U13:U17")
    )
  ) fail("warningDisposition");
}

function pinnedSourcePath(datasetDirectory, manifest, definition) {
  const filename = manifest?.source?.filename;
  if (
    typeof filename !== "string" || isAbsolute(filename) || basename(filename) !== filename ||
    filename === "." || filename === ".."
  ) throw new Error(`LEGACY_SOURCE_PATH_INVALID ${definition.id}`);
  if (filename !== definition.filename) throw new Error(`LEGACY_SOURCE_FILENAME_MISMATCH ${definition.id}`);
  const sourcePath = resolve(datasetDirectory, filename);
  if (dirname(sourcePath) !== datasetDirectory) throw new Error(`LEGACY_SOURCE_PATH_INVALID ${definition.id}`);
  return sourcePath;
}

async function cachedNumber(zip, manifest, reference) {
  const separator = reference.lastIndexOf("!");
  const sheet = manifest.sheetMap.find((item) => item.name === reference.slice(0, separator));
  if (!sheet) throw new Error(`LEGACY_ORACLE_SHEET_MISSING ${reference}`);
  const coordinate = reference.slice(separator + 1);
  const escaped = coordinate.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const xml = await zipText(zip, sheet.part);
  const body = requireMatch(
    xml, new RegExp(`<c\\s+[^>]*\\br="${escaped}"[^>]*>([\\s\\S]*?)<\\/c>`),
    `LEGACY_ORACLE_CELL_MISSING ${reference}`
  )[1];
  const value = Number(decodeXml(
    requireMatch(body, /<v>([\s\S]*?)<\/v>/, `LEGACY_ORACLE_CACHE_MISSING ${reference}`)[1]
  ));
  if (!Number.isFinite(value)) throw new Error(`LEGACY_ORACLE_CACHE_INVALID ${reference}`);
  return value;
}

async function verifyProfile(datasetDirectory, definition) {
  const manifest = JSON.parse(await readFile(resolve(manifestDirectory, definition.manifest), "utf8"));
  const sourcePath = pinnedSourcePath(datasetDirectory, manifest, definition);
  const digest = sha256(JSON.stringify(canonical(manifest)));
  if (digest !== definition.manifestSha256) {
    throw new Error(`LEGACY_PROFILE_DIGEST_MISMATCH ${definition.id} expected=${definition.manifestSha256} actual=${digest}`);
  }
  validateManifest(manifest, definition);
  let bytes;
  try {
    bytes = await readFile(sourcePath);
  } catch {
    throw new Error(`LEGACY_SOURCE_MISSING ${definition.filename}`);
  }
  const actualSha = sha256(bytes);
  if (manifest.source.sha256 !== definition.sha256 || actualSha !== definition.sha256) {
    throw new Error(`LEGACY_SOURCE_HASH_MISMATCH ${definition.filename} expected=${definition.sha256} actual=${actualSha}`);
  }
  const zip = await JSZip.loadAsync(bytes);
  const inventory = await inspectPackage(zip);
  assertSame(inventory.packageParts, manifest.source.packageParts, `LEGACY_PROFILE_INVENTORY_MISMATCH ${definition.id} packageParts`);
  assertSame(inventory.sheetMap, manifest.sheetMap, `LEGACY_PROFILE_INVENTORY_MISMATCH ${definition.id} sheetMap`);
  assertSame(inventory.baselineInventory, manifest.baselineInventory, `LEGACY_PROFILE_INVENTORY_MISMATCH ${definition.id} baselineInventory`);
  const activeFormula = await activeFormulaInventory(bytes, manifest);
  assertSame(
    activeFormula,
    {
      cellCount: manifest.activeFormula.cellCount,
      ranges: manifest.activeFormula.ranges,
      combinedFingerprint: manifest.activeFormula.combinedFingerprint
    },
    `LEGACY_ACTIVE_FORMULA_MISMATCH ${definition.id}`
  );
  const hasRawFee = Object.hasOwn(manifest.totalOracle, "rawFeeWon");
  for (const [group, field] of [
    ["subtotal", "subtotalWon"],
    [hasRawFee ? "rawFee" : "fee", hasRawFee ? "rawFeeWon" : "feeWon"],
    ["total", "totalWon"]
  ]) {
    for (const reference of manifest.totalOracle.cells[group]) {
      if ((await cachedNumber(zip, manifest, reference)) !== manifest.totalOracle[field]) {
        throw new Error(`LEGACY_TOTAL_ORACLE_MISMATCH ${definition.id} ${reference}`);
      }
    }
  }
  if (manifest.totalOracle.totalWon !== definition.totalWon) {
    throw new Error(`LEGACY_PROFILE_SEMANTIC_MISMATCH ${definition.id} totalOracle`);
  }
  return {
    id: definition.id,
    sheetCount: manifest.sheetMap.length,
    formulaCells: manifest.sheetMap.reduce((sum, sheet) => sum + sheet.formulaCells, 0),
    activeFormulaCells: activeFormula.cellCount,
    externalLinks: manifest.baselineInventory.externalLinks.count,
    capacity: manifest.capacity.rows,
    totalWon: manifest.totalOracle.totalWon,
    formulaFingerprint: activeFormula.combinedFingerprint,
    sourceSha256: actualSha
  };
}

async function main() {
  const args = process.argv.slice(2);
  if (args.length !== 2 || args[0] !== "--verify-only") {
    throw new Error("Usage: node scripts/build-legacy-profiles.mjs --verify-only <dataset-directory>");
  }
  const datasetDirectory = resolve(args[1]);
  try {
    if (!(await stat(datasetDirectory)).isDirectory()) throw new Error("not-directory");
  } catch {
    throw new Error(`LEGACY_DATASET_PATH_INVALID ${datasetDirectory}`);
  }
  const profiles = [];
  for (const definition of profileDefinitions) profiles.push(await verifyProfile(datasetDirectory, definition));
  process.stdout.write(`${JSON.stringify({ status: "PASS", profiles })}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
});
