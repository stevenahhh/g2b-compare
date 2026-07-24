import { canonicalJson, sha256 } from "./canonical.js";
import { OfficialDataError } from "./errors.js";
import { OFFICIAL_EXPECTED } from "./revision.js";
import type {
  MarketPriceRow,
  OfficialSourceManifest,
  ProductivityRow,
  WageRow
} from "./schemas.js";

export type LoadedOfficialDatasets = {
  readonly manifest: OfficialSourceManifest;
  readonly market: {
    readonly rows: readonly MarketPriceRow[];
    readonly bytes: Uint8Array;
  };
  readonly productivity: {
    readonly rows: readonly ProductivityRow[];
    readonly bytes: Uint8Array;
  };
  readonly wages: {
    readonly rows: readonly WageRow[];
    readonly bytes: Uint8Array;
  };
};

type DatasetVerification<T extends object> = {
  readonly dataset: "market" | "productivity" | "wages";
  readonly rows: readonly T[];
  readonly bytes: Uint8Array;
  readonly expectedHash: string;
  readonly expectedEnrichedHash: string;
};

type CanonicalProjection = Record<string, unknown> & {
  specification?: unknown;
  work_code?: unknown;
};

export function verifyOfficialDatasets(input: LoadedOfficialDatasets): void {
  const marketProjection = verifyDataset({
    dataset: "market",
    ...input.market,
    expectedHash: OFFICIAL_EXPECTED.marketSha256,
    expectedEnrichedHash: OFFICIAL_EXPECTED.marketEnrichedSha256
  });
  const productivityProjection = verifyDataset({
    dataset: "productivity",
    ...input.productivity,
    expectedHash: OFFICIAL_EXPECTED.productivitySha256,
    expectedEnrichedHash: OFFICIAL_EXPECTED.productivityEnrichedSha256
  });
  const wagesProjection = verifyDataset({
    dataset: "wages",
    ...input.wages,
    expectedHash: OFFICIAL_EXPECTED.wagesSha256,
    expectedEnrichedHash: OFFICIAL_EXPECTED.wagesEnrichedSha256
  });
  if (
    sha256(
      Buffer.concat([marketProjection, productivityProjection, wagesProjection])
    ) !== OFFICIAL_EXPECTED.compositeSha256
  ) {
    throw new OfficialDataError(
      "OFFICIAL_DATA_COMPOSITE_HASH_MISMATCH",
      "official composite hash drift"
    );
  }
  verifyRows(input);
}

function verifyDataset<T extends object>(
  input: DatasetVerification<T>
): Uint8Array {
  const projection = projectionBytes(input.dataset, input.rows);
  if (sha256(projection) !== input.expectedHash) {
    throw new OfficialDataError(
      "OFFICIAL_DATA_HASH_MISMATCH",
      `${input.dataset} canonical projection drift`
    );
  }
  if (sha256(input.bytes) !== input.expectedEnrichedHash) {
    throw new OfficialDataError(
      "OFFICIAL_DATA_ENRICHED_HASH_MISMATCH",
      `${input.dataset} enriched bytes drift`
    );
  }
  return projection;
}

function projectionBytes<T extends object>(
  dataset: DatasetVerification<T>["dataset"],
  rows: readonly T[]
): Uint8Array {
  const excluded =
    dataset === "productivity"
      ? new Set(["effective_from", "license_id", "source_id"])
      : new Set(["license_id", "source_id"]);
  const text = rows
    .map((row) => {
      const projected: CanonicalProjection = Object.fromEntries(
        Object.entries(row).filter(([key]) => !excluded.has(key))
      );
      if (
        dataset === "market" &&
        (projected.work_code === "IC2600004" ||
          projected.work_code === "IC34E0004") &&
        projected.specification === "SOURCE_DASH_NOT_SPECIFIED"
      ) {
        projected.specification = "-";
      }
      return `${canonicalJson(projected)}\n`;
    })
    .join("");
  return Buffer.from(text);
}

function verifyRows(input: LoadedOfficialDatasets): void {
  if (
    input.market.rows.length !== 64 ||
    input.productivity.rows.length !== 23 ||
    input.wages.rows.length !== 10
  ) {
    throw new OfficialDataError(
      "OFFICIAL_DATA_COUNT_MISMATCH",
      "official row count drift"
    );
  }
  requireUniqueOrdered(
    "market",
    input.market.rows.map((row) => row.work_code),
    true
  );
  requireUniqueOrdered(
    "productivity",
    input.productivity.rows.map(
      (row) =>
        `${row.standard_item}|${row.task}|${row.specification}|${row.unit}`
    ),
    false
  );
  requireUniqueOrdered(
    "wages",
    input.wages.rows.map((row) => row.job_code),
    true
  );
  const sources = new Map(
    input.manifest.sources.map((source) => [source.source_id, source])
  );
  for (const row of [
    ...input.market.rows,
    ...input.productivity.rows,
    ...input.wages.rows
  ]) {
    const source = sources.get(row.source_id);
    if (
      source?.url !== row.source_url ||
      source.pdf_sha256 !== row.source_pdf_sha256 ||
      source.effective_from !== row.effective_from ||
      source.license.identifier !== row.license_id
    ) {
      throw new OfficialDataError(
        "OFFICIAL_DATA_SOURCE_MISMATCH",
        `${row.source_id} row provenance drift`
      );
    }
  }
  const breakdown = {
    CCTV: input.market.rows.filter((row) => row.category === "CCTV").length,
    LAN: input.market.rows.filter((row) => row.category === "LAN").length,
    FIBER: input.market.rows.filter((row) => row.category === "광케이블").length,
    included: input.market.rows.filter((row) => row.material_included).length,
    excluded: input.market.rows.filter((row) => !row.material_included).length
  };
  if (
    canonicalJson(breakdown) !==
    canonicalJson({ CCTV: 22, LAN: 36, FIBER: 6, included: 40, excluded: 24 })
  ) {
    throw new OfficialDataError(
      "OFFICIAL_DATA_COUNT_MISMATCH",
      "market breakdown drift"
    );
  }
}

function requireUniqueOrdered(
  dataset: string,
  keys: readonly string[],
  ordered: boolean
): void {
  if (new Set(keys).size !== keys.length) {
    throw new OfficialDataError(
      "OFFICIAL_DATA_DUPLICATE_SOURCE_ROW",
      `${dataset} duplicate row`
    );
  }
  if (ordered && keys.join("\n") !== [...keys].sort().join("\n")) {
    throw new OfficialDataError(
      "OFFICIAL_DATA_ORDER_MISMATCH",
      `${dataset} order drift`
    );
  }
}
