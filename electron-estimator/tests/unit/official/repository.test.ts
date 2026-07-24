import { cp, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { afterEach, expect, test } from "vitest";
import {
  assertOfficialDataReady,
  loadOfficialRepository,
  type OfficialDataError
} from "../../../src/official/repository.js";

const temporaryDirectories: string[] = [];

async function copyResources(): Promise<string> {
  const directory = await mkdtemp(resolve(tmpdir(), "official-repository-"));
  temporaryDirectories.push(directory);
  await cp(resolve(process.cwd(), "resources"), directory, { recursive: true });
  return directory;
}

afterEach(async () => {
  await Promise.all(
    temporaryDirectories.splice(0).map((directory) =>
      rm(directory, { recursive: true, force: true })
    )
  );
});

test("Given the pinned resources When the official repository loads Then exact counts hashes and provenance are immutable", async () => {
  // Given / When
  const repository = await loadOfficialRepository();

  // Then
  expect(repository.revision).toEqual({
    datasetVersion: "2026-H2-KR-CCTV-LAN-FIBER-v1",
    marketSha256: "607f39517446e9089045ad098bfcb9b998385138f40297b005808785fd59fcb0",
    productivitySha256:
      "567884f2d70c8d15d09f48cd2327ead5146edc6b51dd764a841206395a64f3e6",
    wagesSha256: "5157a575cc3a9f66c302163bd0f2c4b15c9b3b99e8167834fde89f2b54ae03c7",
    compositeSha256:
      "0705bbc698818fd1b291df2c554028253777e10503863fe2564830faf7e3fe16",
    sourceManifestSha256:
      "482309efcfd22ca0cc15dc55c3e08d9b1dc01ae6ef15187946ccdf53fc0f0745"
  });
  expect(repository.marketPrices).toHaveLength(64);
  expect(repository.productivity).toHaveLength(23);
  expect(repository.wages).toHaveLength(10);
  expect(repository.marketBreakdown).toEqual({
    categories: { CCTV: 22, LAN: 36, FIBER: 6 },
    included: 40,
    excluded: 24,
    reasonByState: {
      included: "Official unit price includes material cost.",
      excluded:
        "Official unit price excludes material cost; sourced procurement or user-entered material price remains separate."
    }
  });
  expect(repository.marketPrices.every((row) => row.source_id.length > 0)).toBe(
    true
  );
  expect(
    repository.marketPrices.every(
      (row) =>
        row.source_url.startsWith("https://") &&
        row.source_pdf_page > 0 &&
        row.license_id.length > 0 &&
        row.effective_from.length > 0
    )
  ).toBe(true);
  expect(Object.isFrozen(repository)).toBe(true);
  expect(Object.isFrozen(repository.marketPrices)).toBe(true);
  expect(Object.isFrozen(repository.marketPrices[0])).toBe(true);
});

test("Given the pinned resource root When startup readiness is asserted Then validation completes without a value", async () => {
  await expect(
    assertOfficialDataReady(resolve(process.cwd(), "resources"))
  ).resolves.toBeUndefined();
});

test("Given one tampered canonical market row When app-ready loading runs Then it fails closed on hash drift", async () => {
  // Given
  const rootPath = await copyResources();
  const path = resolve(rootPath, "data", "market-prices.jsonl");
  const text = await readFile(path, "utf8");
  await writeFile(path, text.replace('"unit_price_krw":6251', '"unit_price_krw":6252'));

  // When
  const result = assertOfficialDataReady(rootPath);

  // Then
  await expect(result).rejects.toMatchObject({
    code: "OFFICIAL_DATA_HASH_MISMATCH"
  } satisfies Partial<OfficialDataError>);
});

test("Given formula-like official text When loading runs Then unsafe input is rejected before use", async () => {
  // Given
  const rootPath = await copyResources();
  const path = resolve(rootPath, "data", "market-prices.jsonl");
  const text = await readFile(path, "utf8");
  await writeFile(path, text.replace('"name":"광섬유케이블"', '"name":"=1+1"'));

  // When
  const result = loadOfficialRepository({ rootPath });

  // Then
  await expect(result).rejects.toMatchObject({
    code: "OFFICIAL_DATA_UNSAFE_TEXT"
  } satisfies Partial<OfficialDataError>);
});

test("Given malformed JSONL When loading runs Then app-ready fails closed", async () => {
  // Given
  const rootPath = await copyResources();
  await writeFile(resolve(rootPath, "data", "wages.jsonl"), "{\n");

  // When
  const result = loadOfficialRepository({ rootPath });

  // Then
  await expect(result).rejects.toMatchObject({
    code: "OFFICIAL_DATA_MALFORMED_JSON"
  } satisfies Partial<OfficialDataError>);
});

test("Given source manifest metadata drifts When loading runs Then the pinned manifest hash rejects it", async () => {
  // Given
  const rootPath = await copyResources();
  const path = resolve(rootPath, "sources", "source-manifest.json");
  const text = await readFile(path, "utf8");
  await writeFile(
    path,
    text.replace("한국정보통신산업연구원", "한국정보통신산업연구원 변경")
  );

  // When
  const result = loadOfficialRepository({ rootPath });

  // Then
  await expect(result).rejects.toMatchObject({
    code: "OFFICIAL_DATA_SOURCE_MANIFEST_HASH_MISMATCH"
  } satisfies Partial<OfficialDataError>);
});

test("Given only an enriched provenance field drifts When loading runs Then the enriched hash rejects it", async () => {
  // Given
  const rootPath = await copyResources();
  const path = resolve(rootPath, "data", "market-prices.jsonl");
  const text = await readFile(path, "utf8");
  await writeFile(
    path,
    text.replace(
      '"license_id":"KOGL-TYPE-4"',
      '"license_id":"KOGL-TYPE-4-DRIFT"'
    )
  );

  // When
  const result = loadOfficialRepository({ rootPath });

  // Then
  await expect(result).rejects.toMatchObject({
    code: "OFFICIAL_DATA_ENRICHED_HASH_MISMATCH"
  } satisfies Partial<OfficialDataError>);
});

test("Given a market row also carries productivity fields When loading runs Then repository schema rejects double counting", async () => {
  // Given
  const rootPath = await copyResources();
  const path = resolve(rootPath, "data", "market-prices.jsonl");
  const text = await readFile(path, "utf8");
  await writeFile(
    path,
    text.replace(
      '"category":"광케이블",',
      '"category":"광케이블","coefficients_by_job_code":{"1002":"1"},'
    )
  );

  // When
  const result = loadOfficialRepository({ rootPath });

  // Then
  await expect(result).rejects.toMatchObject({
    code: "OFFICIAL_DATA_ROW_SCHEMA"
  } satisfies Partial<OfficialDataError>);
});

test("Given an interrupted JSONL write When loading runs Then no partial repository is returned", async () => {
  // Given
  const rootPath = await copyResources();
  const path = resolve(rootPath, "data", "wages.jsonl");
  const text = await readFile(path, "utf8");
  await writeFile(path, text.slice(0, -1));

  // When
  const result = loadOfficialRepository({ rootPath });

  // Then
  await expect(result).rejects.toMatchObject({
    code: "OFFICIAL_DATA_INTERRUPTED_GENERATION"
  } satisfies Partial<OfficialDataError>);
});

test("Given the production sourced-product ledger When loaded Then observations and fabricated rows remain zero", async () => {
  // Given / When
  const repository = await loadOfficialRepository();

  // Then
  expect(repository.sourcedProducts).toEqual([]);
  expect(Object.isFrozen(repository.sourcedProducts)).toBe(true);
});

test("Given a manifest claims a synthetic production observation When loading runs Then fabricated production data is rejected", async () => {
  // Given
  const rootPath = await copyResources();
  const path = resolve(rootPath, "observations", "manifest.json");
  const manifest: unknown = JSON.parse(await readFile(path, "utf8"));
  if (manifest === null || typeof manifest !== "object" || Array.isArray(manifest)) {
    expect.fail("Expected observation manifest object");
  }
  await writeFile(path, JSON.stringify({ ...manifest, record_count: 1 }, null, 2));

  // When
  const result = loadOfficialRepository({ rootPath });

  // Then
  await expect(result).rejects.toMatchObject({
    code: "SOURCED_PRODUCTS_LEDGER_INVALID"
  } satisfies Partial<OfficialDataError>);
});

test("Given an unrelated dirty resource file When loading runs Then pinned inputs remain deterministic", async () => {
  // Given
  const rootPath = await copyResources();
  await writeFile(resolve(rootPath, "unrelated-dirty-file.txt"), "ignored");

  // When
  const repository = await loadOfficialRepository({ rootPath });

  // Then
  expect(repository.revision.compositeSha256).toBe(
    "0705bbc698818fd1b291df2c554028253777e10503863fe2564830faf7e3fe16"
  );
});
