#!/usr/bin/env node
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const PROJECT_ROOT = fileURLToPath(new URL("..", import.meta.url));
const OBSERVATION_ROOT = resolve(PROJECT_ROOT, "resources", "observations");
const DEFAULT_MANIFEST = resolve(OBSERVATION_ROOT, "manifest.json");
const SHA256 = /^[0-9a-f]{64}$/u;
const OBSERVED_AT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/u;

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

function requireSafeText(value, path = "$") {
  if (typeof value === "string") {
    const hasControlCharacter = [...value].some(
      (character) => character.codePointAt(0) < 32,
    );
    requireCondition(
      !hasControlCharacter && !/^\s*[=+\-@]/u.test(value),
      "SOURCED_PRODUCTS_UNSAFE_TEXT",
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
      "SOURCED_PRODUCTS_MANIFEST_MISSING",
      `cannot read ${path}`,
    );
  }
  requireCondition(
    !text.startsWith("\uFEFF"),
    "SOURCED_PRODUCTS_NON_CANONICAL_JSON",
    `BOM found in ${path}`,
  );
  try {
    const value = JSON.parse(text);
    requireSafeText(value);
    return value;
  } catch (error) {
    if (error instanceof VerificationError) throw error;
    throw new VerificationError(
      "SOURCED_PRODUCTS_MALFORMED_JSON",
      `malformed JSON in ${path}`,
    );
  }
}

function requireInside(base, target) {
  const pathFromBase = relative(base, target);
  requireCondition(
    pathFromBase !== ".." &&
      !pathFromBase.startsWith(`..\\`) &&
      !pathFromBase.startsWith("../"),
    "SOURCED_PRODUCTS_DIRTY_BOUNDARY",
    `${target} is outside ${base}`,
  );
}

function requireString(row, field, observationId) {
  requireCondition(
    typeof row[field] === "string" && row[field].length > 0,
    "SOURCED_PRODUCTS_ROW_SCHEMA",
    `${observationId}.${field} must be a non-empty string`,
  );
}

function requireEvidence(evidence, field, row) {
  const observationId = row.observation_id;
  requireCondition(
    evidence !== null && typeof evidence === "object" && !Array.isArray(evidence),
    "SOURCED_PRODUCTS_KOREANET_EVIDENCE_MISSING",
    `${observationId}.${field} missing`,
  );
  for (const required of [
    "observed_at",
    "source_payload_sha256",
    "source_url",
    "statement",
  ]) {
    requireString(evidence, required, `${observationId}.${field}`);
  }
  requireCondition(
    OBSERVED_AT.test(evidence.observed_at) &&
      SHA256.test(evidence.source_payload_sha256) &&
      evidence.source_url.startsWith("https://") &&
      evidence.observed_at === row.observed_at &&
      evidence.source_payload_sha256 === row.source_payload_sha256 &&
      evidence.source_url === row.source_url,
    "SOURCED_PRODUCTS_KOREANET_EVIDENCE_INVALID",
    `${observationId}.${field} provenance invalid`,
  );
}

function validateRow(row, fixture) {
  const id =
    typeof row.observation_id === "string" ? row.observation_id : "<unknown>";
  for (const field of [
    "api_operation",
    "observation_id",
    "observed_at",
    "product_id",
    "source_payload_sha256",
    "source_url",
    "spec_snapshot",
    "supplier_name",
    "unit",
  ]) {
    requireString(row, field, id);
  }
  requireCondition(
    Number.isSafeInteger(row.unit_price_won) &&
      row.unit_price_won > 0 &&
      /^[0-9]{8}$/u.test(row.product_id) &&
      row.source_url.startsWith("https://") &&
      OBSERVED_AT.test(row.observed_at) &&
      SHA256.test(row.source_payload_sha256),
    "SOURCED_PRODUCTS_ROW_SCHEMA",
    `${id} price/product/provenance invalid`,
  );
  if (fixture) {
    requireCondition(
      row.synthetic === true,
      "SOURCED_PRODUCTS_FIXTURE_NOT_MARKED_SYNTHETIC",
      `${id} fixture must be marked synthetic`,
    );
  } else {
    requireCondition(
      row.synthetic !== true &&
        row.authenticity?.kind === "captured_source_payload" &&
        row.authenticity.source_payload_sha256 === row.source_payload_sha256,
      "SOURCED_PRODUCTS_UNSOURCED_PRODUCTION_ROW",
      `${id} lacks authentic captured-payload evidence`,
    );
  }
  if (/코리아넷|koreanet/iu.test(row.supplier_name)) {
    requireEvidence(row.supplier_location_evidence, "supplier_location_evidence", row);
    requireEvidence(row.service_area_evidence, "service_area_evidence", row);
  }
}

export function validateSourcedProductRow(row, fixture = false) {
  validateRow(row, fixture);
}

function validateSelectionEvidence(rows) {
  let verified = 0;
  for (const row of rows) {
    if (!row.selection_evidence) continue;
    const evidence = row.selection_evidence;
    requireCondition(
      typeof evidence.comparison_group === "string" &&
        SHA256.test(evidence.specification_fingerprint) &&
        Array.isArray(evidence.compared_observation_ids) &&
        typeof evidence.auto_selected === "boolean" &&
        typeof evidence.eligible === "boolean",
      "SOURCED_PRODUCTS_SELECTION_EVIDENCE_INVALID",
      `${row.observation_id} selection evidence malformed`,
    );
    const comparable = rows.filter(
      (candidate) =>
        candidate.selection_evidence?.comparison_group ===
          evidence.comparison_group &&
        candidate.selection_evidence?.specification_fingerprint ===
          evidence.specification_fingerprint &&
        candidate.selection_evidence?.eligible === true,
    );
    const lowest = Math.min(...comparable.map((candidate) => candidate.unit_price_won));
    const comparedIds = [...new Set(evidence.compared_observation_ids)].sort();
    const comparableIds = comparable
      .map((candidate) => candidate.observation_id)
      .sort();
    requireCondition(
      comparable.length >= 2 &&
        comparedIds.join("\n") === comparableIds.join("\n") &&
        evidence.lowest_observed_unit_price_won === lowest &&
        (!evidence.auto_selected || row.unit_price_won === lowest),
      "SOURCED_PRODUCTS_KOREANET_NOT_LOWEST",
      `${row.observation_id} lowest-only evidence mismatch`,
    );
    if (/코리아넷|koreanet/iu.test(row.supplier_name)) verified += 1;
  }
  return verified;
}

async function readRows(path, expectedHash, expectedCount, format) {
  let bytes;
  try {
    bytes = await readFile(path);
  } catch {
    throw new VerificationError(
      "SOURCED_PRODUCTS_FILE_MISSING",
      `cannot read ${path}`,
    );
  }
  requireCondition(
    bytes.length <= 2_000_000,
    "SOURCED_PRODUCTS_FILE_TOO_LONG",
    `${path} exceeds 2 MB`,
  );
  const text = bytes.toString("utf8");
  requireCondition(
    !text.startsWith("\uFEFF") && !text.includes("\r"),
    "SOURCED_PRODUCTS_INTERRUPTED_GENERATION",
    `${path} must be UTF-8 LF without BOM`,
  );
  let lines;
  if (format === "canonical_json_array_lf") {
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch {
      throw new VerificationError(
        "SOURCED_PRODUCTS_MALFORMED_JSON",
        `malformed JSON in ${path}`,
      );
    }
    requireCondition(
      Array.isArray(parsed) && `${canonical(parsed)}\n` === text,
      "SOURCED_PRODUCTS_NON_CANONICAL_JSON",
      `${path} is not a canonical JSON array`,
    );
    lines = parsed.map(canonical);
  } else {
    requireCondition(
      text.length === 0 || text.endsWith("\n"),
      "SOURCED_PRODUCTS_INTERRUPTED_GENERATION",
      `${path} has no final LF`,
    );
    lines = text.length === 0 ? [] : text.slice(0, -1).split("\n");
  }
  const rows = lines.map((line, index) => {
    requireCondition(
      Buffer.byteLength(line) <= 65_536,
      "SOURCED_PRODUCTS_JSONL_LINE_TOO_LONG",
      `${path}:${index + 1} exceeds 64 KiB`,
    );
    let row;
    try {
      row = JSON.parse(line);
    } catch {
      throw new VerificationError(
        "SOURCED_PRODUCTS_MALFORMED_JSONL",
        `malformed JSON at ${path}:${index + 1}`,
      );
    }
    requireSafeText(row, `$[${index}]`);
    requireCondition(
      canonical(row) === line,
      "SOURCED_PRODUCTS_NON_CANONICAL_JSONL",
      `non-canonical row at ${path}:${index + 1}`,
    );
    return row;
  });
  requireCondition(
    sha256(bytes) === expectedHash,
    "SOURCED_PRODUCTS_HASH_MISMATCH",
    `expected ${expectedHash}, got ${sha256(bytes)}`,
  );
  requireCondition(
    rows.length === expectedCount,
    "SOURCED_PRODUCTS_COUNT_MISMATCH",
    `expected ${expectedCount}, got ${rows.length}`,
  );
  return rows;
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
        "SOURCED_PRODUCTS_ARGUMENT",
        `unknown argument ${argv[index]}`,
      );
  }
  return { fixture, manifest };
}

export async function verifySourcedProducts({ fixture, manifest: manifestPath }) {
  const manifest = await readJson(manifestPath);
  requireCondition(
    manifest.schema_version === "sourced-product-observation-manifest-v1" &&
      SHA256.test(manifest.canonical_sha256) &&
      Number.isSafeInteger(manifest.record_count) &&
      manifest.record_count >= 0,
    "SOURCED_PRODUCTS_MANIFEST_SCHEMA",
    "manifest schema/hash/count invalid",
  );
  requireCondition(
    fixture
      ? manifest.ledger_kind === "synthetic_test_fixture"
      : manifest.ledger_kind === "authentic_production",
    "SOURCED_PRODUCTS_LEDGER_KIND_INVALID",
    "ledger kind does not match invocation",
  );
  const boundary = fixture ? dirname(manifestPath) : OBSERVATION_ROOT;
  const observationPath = resolve(dirname(manifestPath), manifest.observation_file);
  const schemaPath = resolve(dirname(manifestPath), manifest.schema_file);
  requireInside(boundary, observationPath);
  requireInside(boundary, schemaPath);
  const schema = await readJson(schemaPath);
  requireCondition(
    schema.$id === "sourced-product-observation.schema.json" &&
      schema.type === "object",
    "SOURCED_PRODUCTS_SCHEMA_INVALID",
    "observation schema invalid",
  );
  const rows = await readRows(
    observationPath,
    manifest.canonical_sha256,
    manifest.record_count,
    manifest.canonical_format,
  );
  const identities = new Set();
  for (const row of rows) {
    validateRow(row, fixture);
    requireCondition(
      !identities.has(row.observation_id),
      "SOURCED_PRODUCTS_DUPLICATE_OBSERVATION",
      `duplicate ${row.observation_id}`,
    );
    identities.add(row.observation_id);
  }
  const koreaNetSelectionEvidence = validateSelectionEvidence(rows);
  requireCondition(
    fixture || manifest.fabricated_rows === 0,
    "SOURCED_PRODUCTS_FABRICATED_ROWS",
    "production manifest must declare fabricated_rows=0",
  );
  return {
    status: "PASS",
    ledger_kind: manifest.ledger_kind,
    observations: rows.length,
    canonical_sha256: manifest.canonical_sha256,
    fabricated_rows: fixture ? rows.length : 0,
    provenance_complete: rows.length,
    koreanet_location_service_evidence: rows.filter((row) =>
      /코리아넷|koreanet/iu.test(row.supplier_name),
    ).length,
    koreanet_lowest_only_evidence: koreaNetSelectionEvidence,
  };
}

async function main() {
  try {
    const report = await verifySourcedProducts(parseArguments(process.argv.slice(2)));
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  } catch (error) {
    const code =
      error instanceof VerificationError
        ? error.code
        : "SOURCED_PRODUCTS_UNEXPECTED_FAILURE";
    process.stderr.write(`${code}: ${error.message}\n`);
    process.exitCode = 1;
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main();
}
