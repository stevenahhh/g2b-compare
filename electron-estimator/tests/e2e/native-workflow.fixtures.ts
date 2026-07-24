import {
  SourcedProductObservationSchema,
  type SourcedProductObservation
} from "../../src/official/schemas.js";

const HASH_A = "a".repeat(64);
const HASH_B = "b".repeat(64);
const HASH_C = "c".repeat(64);
const OBSERVED_AT = "2026-07-23T10:00:00+09:00";

export type CandidateFixture = {
  readonly comparisonGroup: string;
  readonly candidates: readonly SourcedProductObservation[];
};

function observation(
  supplier: "KoreaNet" | "실제 경쟁사",
  price: number,
  productId: string,
  lowest: number,
  group: string,
  suffix: string,
  autoSelected = supplier === "KoreaNet" && price === lowest
): SourcedProductObservation {
  const koreaNet = supplier === "KoreaNet";
  const hash = koreaNet ? HASH_A : HASH_B;
  const sourceUrl = `https://example.test/products/${productId}`;
  const observationId = `${koreaNet ? "koreanet" : "competitor"}-${suffix}`;
  const comparedIds = [`koreanet-${suffix}`, `competitor-${suffix}`];
  return SourcedProductObservationSchema.parse({
    observation_id: observationId,
    product_id: productId,
    supplier_name: supplier,
    unit_price_won: price,
    unit: "EA",
    spec_snapshot: "CCTV 4MP",
    source_url: sourceUrl,
    api_operation: "getProductInfo",
    observed_at: OBSERVED_AT,
    source_payload_sha256: hash,
    authenticity: {
      kind: "captured_source_payload",
      source_payload_sha256: hash
    },
    ...(koreaNet
      ? {
          supplier_location_evidence: {
            statement: "광주 소재 확인",
            source_url: sourceUrl,
            observed_at: OBSERVED_AT,
            source_payload_sha256: hash
          },
          service_area_evidence: {
            statement: "전남 서비스 가능 확인",
            source_url: sourceUrl,
            observed_at: OBSERVED_AT,
            source_payload_sha256: hash
          }
        }
      : {}),
    selection_evidence: {
      comparison_group: group,
      specification_fingerprint: HASH_C,
      eligible: true,
      auto_selected: autoSelected,
      lowest_observed_unit_price_won: lowest,
      compared_observation_ids: comparedIds
    }
  });
}

export const selectedKoreaNetFixture: CandidateFixture = {
  comparisonGroup: "cctv-4mp-camera",
  candidates: [
    observation("KoreaNet", 1_000, "12345678", 1_000, "cctv-4mp-camera", "selected"),
    observation("실제 경쟁사", 1_200, "87654321", 1_000, "cctv-4mp-camera", "selected")
  ]
};

export const lowerAuthenticFixture: CandidateFixture = {
  comparisonGroup: "cctv-4mp-camera-lower",
  candidates: [
    observation("KoreaNet", 1_000, "12345679", 900, "cctv-4mp-camera-lower", "lower"),
    observation("실제 경쟁사", 900, "87654322", 900, "cctv-4mp-camera-lower", "lower")
  ]
};

export const noComparableFixture: CandidateFixture = {
  comparisonGroup: "cctv-4mp-camera-no-comparable",
  candidates: [
    observation(
      "KoreaNet",
      1_000,
      "12345680",
      1_000,
      "cctv-4mp-camera-no-comparable",
      "no-comparable",
      false
    )
  ]
};

export const trustedCandidateFixtures = Object.freeze([
  ...selectedKoreaNetFixture.candidates,
  ...lowerAuthenticFixture.candidates,
  ...noComparableFixture.candidates
]);
