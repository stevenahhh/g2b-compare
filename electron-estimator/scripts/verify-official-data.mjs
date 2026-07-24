#!/usr/bin/env node
import { createHash } from "node:crypto";
import { readdir, readFile } from "node:fs/promises";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const PROJECT_ROOT = fileURLToPath(new URL("..", import.meta.url));
const DATA_ROOT = resolve(PROJECT_ROOT, "resources", "data");
const DEFAULT_MANIFEST = resolve(
  PROJECT_ROOT,
  "resources",
  "sources",
  "source-manifest.json",
);
const EXPECTED = {
  datasetVersion: "2026-H2-KR-CCTV-LAN-FIBER-v1",
  sourceManifestSha256:
    "482309efcfd22ca0cc15dc55c3e08d9b1dc01ae6ef15187946ccdf53fc0f0745",
  compositeSha256:
    "0705bbc698818fd1b291df2c554028253777e10503863fe2564830faf7e3fe16",
  files: {
    market: {
      count: 64,
      effectiveFrom: "2026-07-01",
      enrichedSha256:
        "83c4b7e782692b1aaa95297e10ba219a9a75982cf4c675c15ba325e1b7afdf9b",
      file: "market-prices.jsonl",
      kind: "market_price",
      licenseId: "KOGL-TYPE-4",
      sha256:
        "607f39517446e9089045ad098bfcb9b998385138f40297b005808785fd59fcb0",
      sourceId: "KICI_2026_H2_MARKET_PRICE",
    },
    productivity: {
      count: 23,
      effectiveFrom: "2026-01-01",
      enrichedSha256:
        "2f0d4aaf3e125e6472fc19842a8499dfc05d33c57fa0daeebe2ead9001335bf0",
      file: "productivity.jsonl",
      kind: "standard_productivity",
      licenseId: "KOGL-TYPE-4",
      sha256:
        "567884f2d70c8d15d09f48cd2327ead5146edc6b51dd764a841206395a64f3e6",
      sourceId: "KICI_2026_STANDARD_PRODUCTIVITY",
    },
    wages: {
      count: 10,
      effectiveFrom: "2026-01-01",
      enrichedSha256:
        "f362090a2c9588d64ceae263beca9a978778ab083d1a7106ac152d3316070e76",
      file: "wages.jsonl",
      kind: "wage_rate",
      licenseId: "SOURCE_TERMS_NOT_ESTABLISHED",
      sha256:
        "5157a575cc3a9f66c302163bd0f2c4b15c9b3b99e8167834fde89f2b54ae03c7",
      sourceId: "CAK_2026_H1_WAGE",
    },
  },
  pdfHashes: new Set([
    "7c00add21c816c4118d9851d555889a6fd650679ddc65c3f420e007273f5d721",
    "a77f45dfe5f1b95891d169f65b6eef25e4d6e72e06f2d4831fc0e2c858079a9e",
    "b763ac6a64a245e633657e20d8625728c86ed215b3e75e16f6258e9230be9c8f",
  ]),
  wages: new Map([
    ["1002", 172068],
    ["1003", 226122],
    ["1086", 284880],
    ["1087", 315528],
    ["1088", 408942],
    ["1089", 436224],
    ["2001", 471349],
    ["2002", 393090],
    ["2003", 446358],
    ["5002", 304509],
  ]),
};
const EXPECTED_PROJECTION = {
  checksum_field: "sha256",
  enriched_checksum_field: "enriched_sha256",
  excluded_fields_by_dataset: {
    market: ["license_id", "source_id"],
    productivity: ["effective_from", "license_id", "source_id"],
    wages: ["license_id", "source_id"],
  },
  normalizations: [
    {
      canonical_code_point: 45,
      dataset: "market",
      enriched_value: "SOURCE_DASH_NOT_SPECIFIED",
      field: "specification",
      work_codes: ["IC2600004", "IC34E0004"],
    },
  ],
  purpose:
    "Preserves the mandated canonical rate-content checksums while the enriched file checksum covers direct row provenance.",
};
const SHA256 = /^[0-9a-f]{64}$/u;
const HTTPS = /^https:\/\//u;

class VerificationError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "VerificationError";
    this.code = code;
  }
}

function requireCondition(condition, code, message) {
  if (!condition) throw new VerificationError(code, message);
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function sourceManifestSha256(manifest) {
  const unsigned = { ...manifest };
  delete unsigned.source_manifest_sha256;
  return sha256(canonical(unsigned));
}

function projectRow(dataset, row) {
  const projected = { ...row };
  for (const normalization of EXPECTED_PROJECTION.normalizations) {
    if (
      normalization.dataset === dataset &&
      normalization.work_codes.includes(projected.work_code) &&
      projected[normalization.field] === normalization.enriched_value
    ) {
      projected[normalization.field] = String.fromCodePoint(
        normalization.canonical_code_point,
      );
    }
  }
  for (const field of EXPECTED_PROJECTION.excluded_fields_by_dataset[dataset]) {
    delete projected[field];
  }
  return projected;
}

function requireSafeText(value, path = "$") {
  if (typeof value === "string") {
    const hasControlCharacter = [...value].some(
      (character) => character.codePointAt(0) < 32,
    );
    requireCondition(
      !hasControlCharacter && !/^\s*[=+\-@]/u.test(value),
      "OFFICIAL_DATA_UNSAFE_TEXT",
      `unsafe text at ${path}`,
    );
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((item, index) => {
      requireSafeText(item, `${path}[${index}]`);
    });
    return;
  }
  if (value !== null && typeof value === "object") {
    Object.entries(value).forEach(([key, item]) => {
      requireSafeText(item, `${path}.${key}`);
    });
  }
}

async function readJson(path) {
  let text;
  try {
    text = await readFile(path, "utf8");
  } catch {
    throw new VerificationError(
      "OFFICIAL_DATA_MANIFEST_MISSING",
      `cannot read ${path}`,
    );
  }
  requireCondition(
    !text.startsWith("\uFEFF"),
    "OFFICIAL_DATA_BOM_FORBIDDEN",
    `BOM found in ${path}`,
  );
  try {
    const value = JSON.parse(text);
    requireSafeText(value);
    return value;
  } catch (error) {
    if (error instanceof VerificationError) throw error;
    throw new VerificationError(
      "OFFICIAL_DATA_MALFORMED_JSON",
      `malformed JSON in ${path}`,
    );
  }
}

function requireInside(base, target, code) {
  const pathFromBase = relative(base, target);
  requireCondition(
    pathFromBase !== ".." &&
      !pathFromBase.startsWith(`..\\`) &&
      !pathFromBase.startsWith("../") &&
      !resolve(target).startsWith(`${resolve(base)}..`),
    code,
    `${target} is outside ${base}`,
  );
}

async function readRows(path, fileSpec) {
  let bytes;
  try {
    bytes = await readFile(path);
  } catch {
    throw new VerificationError(
      "OFFICIAL_DATA_FILE_MISSING",
      `cannot read ${path}`,
    );
  }
  requireCondition(
    bytes.length <= 2_000_000,
    "OFFICIAL_DATA_FILE_TOO_LONG",
    `${path} exceeds 2 MB`,
  );
  const text = bytes.toString("utf8");
  requireCondition(
    !text.startsWith("\uFEFF") && !text.includes("\r"),
    "OFFICIAL_DATA_NON_CANONICAL_JSONL",
    `${path} must be UTF-8 LF without BOM`,
  );
  requireCondition(
    text.length === 0 || text.endsWith("\n"),
    "OFFICIAL_DATA_INTERRUPTED_GENERATION",
    `${path} has no final LF`,
  );
  const lines = text.length === 0 ? [] : text.slice(0, -1).split("\n");
  const rows = lines.map((line, index) => {
    requireCondition(
      Buffer.byteLength(line) <= 65_536,
      "OFFICIAL_DATA_JSONL_LINE_TOO_LONG",
      `${path}:${index + 1} exceeds 64 KiB`,
    );
    let row;
    try {
      row = JSON.parse(line);
    } catch {
      throw new VerificationError(
        "OFFICIAL_DATA_MALFORMED_JSONL",
        `malformed JSON at ${path}:${index + 1}`,
      );
    }
    requireCondition(
      row !== null && typeof row === "object" && !Array.isArray(row),
      "OFFICIAL_DATA_ROW_SCHEMA",
      `row ${index + 1} must be an object`,
    );
    requireSafeText(row, `$[${index}]`);
    requireCondition(
      canonical(row) === line,
      "OFFICIAL_DATA_NON_CANONICAL_JSONL",
      `non-canonical row at ${path}:${index + 1}`,
    );
    requireCondition(
      row.kind === fileSpec.kind,
      "OFFICIAL_DATA_ROW_SCHEMA",
      `unexpected kind at ${path}:${index + 1}`,
    );
    return row;
  });
  requireCondition(
    rows.length === fileSpec.record_count,
    "OFFICIAL_DATA_COUNT_MISMATCH",
    `${fileSpec.dataset}: expected ${fileSpec.record_count}, got ${rows.length}`,
  );
  const projectionBytes = Buffer.from(
    rows.map((row) => `${canonical(projectRow(fileSpec.dataset, row))}\n`).join(""),
  );
  requireCondition(
    sha256(projectionBytes) === fileSpec.sha256,
    "OFFICIAL_DATA_HASH_MISMATCH",
    `${fileSpec.dataset}: canonical projection checksum mismatch`,
  );
  requireCondition(
    sha256(bytes) === fileSpec.enriched_sha256,
    "OFFICIAL_DATA_ENRICHED_HASH_MISMATCH",
    `${fileSpec.dataset}: enriched file checksum mismatch`,
  );
  return { bytes, projectionBytes, rows };
}

function requireString(row, field, dataset) {
  requireCondition(
    typeof row[field] === "string" && row[field].length > 0,
    "OFFICIAL_DATA_ROW_SCHEMA",
    `${dataset}.${field} must be a non-empty string`,
  );
}

function validateRows(dataset, rows, sourceById) {
  const identity = new Set();
  const orderedKeys = [];
  for (const row of rows) {
    for (const field of [
      "effective_from",
      "jurisdiction",
      "license_id",
      "source_id",
      "source_pdf_sha256",
      "source_url",
    ]) {
      requireString(row, field, dataset);
    }
    requireCondition(
      row.jurisdiction === "KR_NATIONWIDE" &&
        SHA256.test(row.source_pdf_sha256) &&
        HTTPS.test(row.source_url),
      "OFFICIAL_DATA_ROW_SCHEMA",
      `${dataset} has invalid provenance`,
    );
    if (sourceById) {
      const expected = EXPECTED.files[dataset];
      const source = sourceById.get(row.source_id);
      requireCondition(
        row.source_id === expected.sourceId &&
          row.effective_from === expected.effectiveFrom &&
          row.license_id === expected.licenseId &&
          source?.effective_from === row.effective_from &&
          source?.license?.identifier === row.license_id &&
          source?.pdf_sha256 === row.source_pdf_sha256 &&
          source?.url === row.source_url,
        "OFFICIAL_DATA_ROW_SOURCE_MISMATCH",
        `${dataset} row provenance does not match its pinned source`,
      );
    }
    let key;
    if (dataset === "market") {
      for (const field of [
        "application_scope",
        "category",
        "name",
        "specification",
        "unit",
        "work_code",
      ]) {
        requireString(row, field, dataset);
      }
      requireCondition(
        typeof row.material_included === "boolean" &&
          Number.isInteger(row.unit_price_krw) &&
          row.unit_price_krw > 0 &&
          Number.isInteger(row.source_pdf_page) &&
          row.source_pdf_page > 0,
        "OFFICIAL_DATA_ROW_SCHEMA",
        `${dataset} has invalid price/page/material fields`,
      );
      key = row.work_code;
    } else if (dataset === "productivity") {
      for (const field of [
        "category",
        "specification",
        "standard_item",
        "task",
        "unit",
      ]) {
        requireString(row, field, dataset);
      }
      requireCondition(
        row.standard_year === 2026 &&
          Array.isArray(row.source_pdf_pages) &&
          row.source_pdf_pages.length > 0 &&
          Object.keys(row.coefficients_by_job_code).length > 0,
        "OFFICIAL_DATA_ROW_SCHEMA",
        `${dataset} has invalid year/pages/coefficients`,
      );
      key = `${row.standard_item}|${row.task}|${row.specification}|${row.unit}`;
    } else {
      for (const field of ["effective_from", "job_code", "job_name"]) {
        requireString(row, field, dataset);
      }
      requireCondition(
        Number.isInteger(row.daily_wage_krw) &&
          row.daily_wage_krw > 0 &&
          Array.isArray(row.source_pdf_pages) &&
          row.source_pdf_pages.length > 0,
        "OFFICIAL_DATA_ROW_SCHEMA",
        `${dataset} has invalid wage/pages`,
      );
      key = row.job_code;
    }
    requireCondition(
      !identity.has(key),
      "OFFICIAL_DATA_DUPLICATE_SOURCE_ROW",
      `${dataset} duplicate ${key}`,
    );
    identity.add(key);
    orderedKeys.push(key);
  }
  if (dataset === "market" || dataset === "wages") {
    requireCondition(
      orderedKeys.join("\n") === [...orderedKeys].sort().join("\n"),
      "OFFICIAL_DATA_ORDER_MISMATCH",
      `${dataset} rows are not in canonical order`,
    );
  }
}

async function findBundledPdfs(directory) {
  const found = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.name === "dist") continue;
    const path = resolve(directory, entry.name);
    if (entry.isDirectory()) found.push(...(await findBundledPdfs(path)));
    else if (entry.name.toLowerCase().endsWith(".pdf")) found.push(path);
  }
  return found;
}

function parseArguments(argv) {
  let manifest = DEFAULT_MANIFEST;
  let fixture = false;
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === "--manifest" && argv[index + 1]) {
      manifest = resolve(argv[index + 1]);
      index += 1;
    } else if (argv[index] === "--fixture") fixture = true;
    else
      throw new VerificationError(
        "OFFICIAL_DATA_ARGUMENT",
        `unknown argument ${argv[index]}`,
      );
  }
  return { fixture, manifest };
}

export async function verifyOfficialData({ fixture, manifest: manifestPath }) {
  const manifest = await readJson(manifestPath);
  requireCondition(
    manifest.schema_version === "official-source-manifest-v1" &&
      Array.isArray(manifest.files) &&
      manifest.files.length === 3,
    "OFFICIAL_DATA_MANIFEST_SCHEMA",
    "manifest schema/files invalid",
  );
  let sourceById = null;
  if (!fixture) {
    for (const fileSpec of manifest.files) {
      const expected = EXPECTED.files[fileSpec.dataset];
      requireCondition(
        expected !== undefined,
        "OFFICIAL_DATA_MANIFEST_SCHEMA",
        `unknown dataset ${fileSpec.dataset}`,
      );
      requireCondition(
        fileSpec.sha256 === expected.sha256,
        "OFFICIAL_DATA_HASH_MISMATCH",
        `${fileSpec.dataset}: manifest checksum drift`,
      );
      requireCondition(
        fileSpec.enriched_sha256 === expected.enrichedSha256,
        "OFFICIAL_DATA_ENRICHED_HASH_MISMATCH",
        `${fileSpec.dataset}: enriched manifest checksum drift`,
      );
    }
    requireCondition(
      manifest.source_manifest_sha256 === EXPECTED.sourceManifestSha256 &&
        sourceManifestSha256(manifest) === EXPECTED.sourceManifestSha256,
      "OFFICIAL_DATA_SOURCE_MANIFEST_HASH_MISMATCH",
      "source manifest metadata checksum drift",
    );
    requireCondition(
      canonical(manifest.canonical_projection) === canonical(EXPECTED_PROJECTION),
      "OFFICIAL_DATA_PROJECTION_MANIFEST_DRIFT",
      "canonical projection definition drift",
    );
    const sources = manifest.sources;
    requireCondition(
      Array.isArray(sources) &&
        new Set(sources.map((source) => source.source_id)).size === 3 &&
        new Set(sources.map((source) => source.pdf_sha256)).size === 3 &&
        sources.every(
          (source) =>
            EXPECTED.pdfHashes.has(source.pdf_sha256) &&
            source.bundled === false &&
            source.effective_from &&
            source.license &&
            Array.isArray(source.sections) &&
            source.sections.length > 0,
        ),
      "OFFICIAL_DATA_SOURCE_MANIFEST_INVALID",
      "source hashes/licenses/effective dates/sections invalid",
    );
    sourceById = new Map(sources.map((source) => [source.source_id, source]));
  }
  const datasets = new Map();
  for (const fileSpec of manifest.files) {
    const expected = EXPECTED.files[fileSpec.dataset];
    requireCondition(
      expected !== undefined,
      "OFFICIAL_DATA_MANIFEST_SCHEMA",
      `unknown dataset ${fileSpec.dataset}`,
    );
    const dataPath = resolve(dirname(manifestPath), fileSpec.path);
    requireInside(fixture ? dirname(manifestPath) : DATA_ROOT, dataPath, "OFFICIAL_DATA_DIRTY_BOUNDARY");
    if (!fixture) {
      requireCondition(
        manifest.dataset_version === EXPECTED.datasetVersion &&
          fileSpec.record_count === expected.count &&
          fileSpec.kind === expected.kind &&
          dataPath === resolve(DATA_ROOT, expected.file),
        "OFFICIAL_DATA_MANIFEST_DRIFT",
        `${fileSpec.dataset} manifest drift`,
      );
    }
    const loaded = await readRows(dataPath, fileSpec);
    validateRows(fileSpec.dataset, loaded.rows, sourceById);
    datasets.set(fileSpec.dataset, loaded);
  }
  requireCondition(
    datasets.size === 3,
    "OFFICIAL_DATA_MANIFEST_SCHEMA",
    "duplicate or missing dataset specs",
  );
  const composite = Buffer.concat([
    datasets.get("market").projectionBytes,
    datasets.get("productivity").projectionBytes,
    datasets.get("wages").projectionBytes,
  ]);
  requireCondition(
    sha256(composite) === manifest.composite_sha256 &&
      (fixture || manifest.composite_sha256 === EXPECTED.compositeSha256),
    "OFFICIAL_DATA_COMPOSITE_HASH_MISMATCH",
    "composite checksum mismatch",
  );
  const marketRows = datasets.get("market").rows;
  const wages = datasets.get("wages").rows;
  const marketCounts = {
    CCTV: marketRows.filter((row) => row.category === "CCTV").length,
    LAN: marketRows.filter((row) => row.category === "LAN").length,
    FIBER: marketRows.filter((row) => row.category === "광케이블").length,
    included: marketRows.filter((row) => row.material_included).length,
    excluded: marketRows.filter((row) => !row.material_included).length,
  };
  if (!fixture) {
    requireCondition(
      canonical(marketCounts) ===
        canonical({ CCTV: 22, FIBER: 6, LAN: 36, excluded: 24, included: 40 }),
      "OFFICIAL_DATA_COUNT_MISMATCH",
      "market breakdown mismatch",
    );
    requireCondition(
      wages.length === EXPECTED.wages.size &&
        wages.every(
          (row) => EXPECTED.wages.get(row.job_code) === row.daily_wage_krw,
        ),
      "OFFICIAL_DATA_WAGE_MISMATCH",
      "fixed wage codes/values mismatch",
    );
  }
  const pdfs = await findBundledPdfs(PROJECT_ROOT);
  requireCondition(
    pdfs.length === 0,
    "OFFICIAL_DATA_PDF_BUNDLED",
    `bundled PDFs: ${pdfs.join(", ")}`,
  );
  return {
    status: "PASS",
    DATASET_VERSION: manifest.dataset_version,
    counts: {
      market: marketRows.length,
      productivity: datasets.get("productivity").rows.length,
      wages: wages.length,
    },
    market_counts: marketCounts,
    checksums: {
      market: manifest.files.find((file) => file.dataset === "market").sha256,
      productivity: manifest.files.find(
        (file) => file.dataset === "productivity",
      ).sha256,
      wages: manifest.files.find((file) => file.dataset === "wages").sha256,
      composite: manifest.composite_sha256,
    },
    enriched_checksums: Object.fromEntries(
      manifest.files.map((file) => [file.dataset, file.enriched_sha256]),
    ),
    composite_sha: manifest.composite_sha256,
    source_manifest_sha256: manifest.source_manifest_sha256,
    direct_provenance_rows: [...datasets.values()].reduce(
      (count, dataset) => count + dataset.rows.length,
      0,
    ),
    duplicate_source_rows: 0,
    pdf_bundled: 0,
    wage_codes_verified: fixture ? null : EXPECTED.wages.size,
  };
}

async function main() {
  try {
    const report = await verifyOfficialData(parseArguments(process.argv.slice(2)));
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  } catch (error) {
    const code =
      error instanceof VerificationError
        ? error.code
        : "OFFICIAL_DATA_UNEXPECTED_FAILURE";
    process.stderr.write(`${code}: ${error.message}\n`);
    process.exitCode = 1;
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main();
}
