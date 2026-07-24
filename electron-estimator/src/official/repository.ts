import { fileURLToPath } from "node:url";
import {
  canonicalJson,
  readCanonicalJson,
  readCanonicalJsonArray,
  readCanonicalJsonl,
  sha256
} from "./canonical.js";
import { OfficialDataError } from "./errors.js";
import { OFFICIAL_EXPECTED } from "./revision.js";
import {
  type MarketPriceRow,
  MarketPriceRowSchema,
  type OfficialSourceManifest,
  OfficialSourceManifestSchema,
  type ProductivityRow,
  ProductivityRowSchema,
  type SourcedProductObservation,
  SourcedProductObservationSchema,
  SourcedProductsManifestSchema,
  type WageRow,
  WageRowSchema
} from "./schemas.js";
import { verifyOfficialDatasets } from "./verification.js";

export { OfficialDataError } from "./errors.js";

const DEFAULT_ROOT = fileURLToPath(new URL("../../resources/", import.meta.url));

export type OfficialRepositoryOptions = {
  readonly rootPath: string;
};

export type OfficialRepository = {
  readonly revision: {
    readonly datasetVersion: typeof OFFICIAL_EXPECTED.datasetVersion;
    readonly marketSha256: typeof OFFICIAL_EXPECTED.marketSha256;
    readonly productivitySha256: typeof OFFICIAL_EXPECTED.productivitySha256;
    readonly wagesSha256: typeof OFFICIAL_EXPECTED.wagesSha256;
    readonly compositeSha256: typeof OFFICIAL_EXPECTED.compositeSha256;
    readonly sourceManifestSha256: typeof OFFICIAL_EXPECTED.sourceManifestSha256;
  };
  readonly marketPrices: readonly MarketPriceRow[];
  readonly productivity: readonly ProductivityRow[];
  readonly wages: readonly WageRow[];
  readonly marketBreakdown: {
    readonly categories: {
      readonly CCTV: 22;
      readonly LAN: 36;
      readonly FIBER: 6;
    };
    readonly included: 40;
    readonly excluded: 24;
    readonly reasonByState: {
      readonly included: string;
      readonly excluded: string;
    };
  };
  readonly sourcedProducts: readonly SourcedProductObservation[];
};

export async function loadOfficialRepository(
  options: OfficialRepositoryOptions = { rootPath: DEFAULT_ROOT }
): Promise<OfficialRepository> {
  const root = new URL(`file:///${options.rootPath.replaceAll("\\", "/")}/`);
  const manifestResult = await readCanonicalJson(
    fileURLToPath(new URL("sources/source-manifest.json", root)),
    OfficialSourceManifestSchema
  );
  verifyManifest(manifestResult.parsed, manifestResult.raw);

  const market = await readCanonicalJsonl(
    fileURLToPath(new URL("data/market-prices.jsonl", root)),
    MarketPriceRowSchema
  );
  const productivity = await readCanonicalJsonl(
    fileURLToPath(new URL("data/productivity.jsonl", root)),
    ProductivityRowSchema
  );
  const wages = await readCanonicalJsonl(
    fileURLToPath(new URL("data/wages.jsonl", root)),
    WageRowSchema
  );
  verifyOfficialDatasets({
    manifest: manifestResult.parsed,
    market,
    productivity,
    wages
  });
  const sourcedProducts = await loadSourcedProducts(root);

  return Object.freeze({
    revision: Object.freeze({
      datasetVersion: OFFICIAL_EXPECTED.datasetVersion,
      marketSha256: OFFICIAL_EXPECTED.marketSha256,
      productivitySha256: OFFICIAL_EXPECTED.productivitySha256,
      wagesSha256: OFFICIAL_EXPECTED.wagesSha256,
      compositeSha256: OFFICIAL_EXPECTED.compositeSha256,
      sourceManifestSha256: OFFICIAL_EXPECTED.sourceManifestSha256
    }),
    marketPrices: market.rows,
    productivity: productivity.rows,
    wages: wages.rows,
    marketBreakdown: Object.freeze({
      categories: Object.freeze({ CCTV: 22, LAN: 36, FIBER: 6 }),
      included: 40,
      excluded: 24,
      reasonByState: Object.freeze({
        included:
          manifestResult.parsed.market_breakdown.reason_by_state.included,
        excluded:
          manifestResult.parsed.market_breakdown.reason_by_state.excluded
      })
    }),
    sourcedProducts
  });
}

export async function assertOfficialDataReady(
  resourceRoot: string
): Promise<void> {
  await loadOfficialRepository({ rootPath: resourceRoot });
}

function verifyManifest(
  manifest: OfficialSourceManifest,
  raw: Readonly<Record<string, unknown>>
): void {
  const unsigned = Object.fromEntries(
    Object.entries(raw).filter(([key]) => key !== "source_manifest_sha256")
  );
  if (
    manifest.dataset_version !== OFFICIAL_EXPECTED.datasetVersion ||
    manifest.composite_sha256 !== OFFICIAL_EXPECTED.compositeSha256 ||
    manifest.source_manifest_sha256 !== OFFICIAL_EXPECTED.sourceManifestSha256 ||
    sha256(canonicalJson(unsigned)) !== OFFICIAL_EXPECTED.sourceManifestSha256
  ) {
    throw new OfficialDataError(
      "OFFICIAL_DATA_SOURCE_MANIFEST_HASH_MISMATCH",
      "source manifest metadata drift"
    );
  }
  const expectedFiles = [
    [
      "market",
      OFFICIAL_EXPECTED.marketSha256,
      OFFICIAL_EXPECTED.marketEnrichedSha256,
      64
    ],
    [
      "productivity",
      OFFICIAL_EXPECTED.productivitySha256,
      OFFICIAL_EXPECTED.productivityEnrichedSha256,
      23
    ],
    [
      "wages",
      OFFICIAL_EXPECTED.wagesSha256,
      OFFICIAL_EXPECTED.wagesEnrichedSha256,
      10
    ]
  ] as const;
  for (const [dataset, hash, enrichedHash, count] of expectedFiles) {
    const file = manifest.files.find((item) => item.dataset === dataset);
    if (
      file?.sha256 !== hash ||
      file.enriched_sha256 !== enrichedHash ||
      file.record_count !== count
    ) {
      throw new OfficialDataError(
        "OFFICIAL_DATA_SOURCE_MANIFEST_HASH_MISMATCH",
        `${dataset} manifest drift`
      );
    }
  }
}

async function loadSourcedProducts(
  root: URL
): Promise<readonly SourcedProductObservation[]> {
  const manifest = await readCanonicalJson(
    fileURLToPath(new URL("observations/manifest.json", root)),
    SourcedProductsManifestSchema
  );
  if (
    manifest.parsed.record_count !== 0 ||
    manifest.parsed.fabricated_rows !== 0 ||
    manifest.parsed.canonical_sha256 !== OFFICIAL_EXPECTED.observationSha256
  ) {
    throw new OfficialDataError(
      "SOURCED_PRODUCTS_LEDGER_INVALID",
      "production observation manifest drift"
    );
  }
  const observations = await readCanonicalJsonArray(
    fileURLToPath(new URL("observations/observations.json", root)),
    SourcedProductObservationSchema
  );
  if (sha256(observations.bytes) !== OFFICIAL_EXPECTED.observationSha256) {
    throw new OfficialDataError(
      "SOURCED_PRODUCTS_HASH_MISMATCH",
      "production observation hash drift"
    );
  }
  if (
    observations.rows.length !== manifest.parsed.record_count ||
    observations.rows.some((row) => row.synthetic === true)
  ) {
    throw new OfficialDataError(
      "SOURCED_PRODUCTS_FABRICATED_ROWS",
      "synthetic production observations are forbidden"
    );
  }
  return observations.rows;
}
