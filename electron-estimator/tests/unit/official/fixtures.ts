export const SOURCE_HASH = "a".repeat(64);
export const OTHER_SOURCE_HASH = "b".repeat(64);
export const SPECIFICATION_HASH = "c".repeat(64);

export const KOREANET_OBSERVATION = {
  observation_id: "koreanet-a",
  product_id: "12345678",
  supplier_name: "KoreaNet",
  unit_price_won: 1000,
  unit: "EA",
  spec_snapshot: "CCTV 4MP",
  source_url: "https://example.test/products/12345678",
  api_operation: "getProductInfo",
  observed_at: "2026-07-23T10:00:00+09:00",
  source_payload_sha256: SOURCE_HASH,
  authenticity: {
    kind: "captured_source_payload",
    source_payload_sha256: SOURCE_HASH
  },
  supplier_location_evidence: {
    statement: "Gwangju office",
    source_url: "https://example.test/products/12345678",
    observed_at: "2026-07-23T10:00:00+09:00",
    source_payload_sha256: SOURCE_HASH
  },
  service_area_evidence: {
    statement: "Jeonnam service",
    source_url: "https://example.test/products/12345678",
    observed_at: "2026-07-23T10:00:00+09:00",
    source_payload_sha256: SOURCE_HASH
  },
  selection_evidence: {
    comparison_group: "cctv-4mp-camera",
    specification_fingerprint: SPECIFICATION_HASH,
    eligible: true,
    auto_selected: true,
    lowest_observed_unit_price_won: 1000,
    compared_observation_ids: ["koreanet-a", "competitor-a"]
  },
  synthetic: true
} as const;

export const COMPETITOR_OBSERVATION = {
  observation_id: "competitor-a",
  product_id: "87654321",
  supplier_name: "Authentic Supplier",
  unit_price_won: 1100,
  unit: "EA",
  spec_snapshot: "CCTV 4MP",
  source_url: "https://example.test/products/87654321",
  api_operation: "getProductInfo",
  observed_at: "2026-07-23T10:01:00+09:00",
  source_payload_sha256: OTHER_SOURCE_HASH,
  authenticity: {
    kind: "captured_source_payload",
    source_payload_sha256: OTHER_SOURCE_HASH
  },
  selection_evidence: {
    comparison_group: "cctv-4mp-camera",
    specification_fingerprint: SPECIFICATION_HASH,
    eligible: true,
    auto_selected: false,
    lowest_observed_unit_price_won: 1000,
    compared_observation_ids: ["koreanet-a", "competitor-a"]
  },
  synthetic: true
} as const;

export const SELECTION_TARGET = {
  requestedItemKey: "cctv-4mp-camera",
  specification: "CCTV 4MP",
  unit: "EA"
} as const;
