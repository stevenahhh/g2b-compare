import { loadOfficialRepository } from "../../src/official/repository.js";
import type { SourcedProductObservation } from "../../src/official/schemas.js";
import { selectKoreaNetCandidate } from "../../src/official/selector.js";

// allow: SIZE_OK – canonical mixed-domain fixture data remains reviewable together.
const HASH_A = "a".repeat(64);
const HASH_B = "b".repeat(64);
const HASH_C = "c".repeat(64);
const OBSERVED_AT = "2026-07-23T10:00:00+09:00";

const koreaNet: SourcedProductObservation = {
  observation_id: "koreanet-native",
  product_id: "12345678",
  supplier_name: "KoreaNet",
  unit_price_won: 1000,
  unit: "EA",
  spec_snapshot: "CCTV 4MP",
  source_url: "https://example.test/products/12345678",
  api_operation: "getProductInfo",
  observed_at: OBSERVED_AT,
  source_payload_sha256: HASH_A,
  authenticity: {
    kind: "captured_source_payload",
    source_payload_sha256: HASH_A
  },
  supplier_location_evidence: {
    statement: "광주 소재 확인",
    source_url: "https://example.test/products/12345678",
    observed_at: OBSERVED_AT,
    source_payload_sha256: HASH_A
  },
  service_area_evidence: {
    statement: "전남 서비스 가능 확인",
    source_url: "https://example.test/products/12345678",
    observed_at: OBSERVED_AT,
    source_payload_sha256: HASH_A
  },
  selection_evidence: {
    comparison_group: "cctv-4mp-camera",
    specification_fingerprint: HASH_C,
    eligible: true,
    auto_selected: true,
    lowest_observed_unit_price_won: 1000,
    compared_observation_ids: ["koreanet-native", "competitor-native"]
  }
};

const competitor: SourcedProductObservation = {
  observation_id: "competitor-native",
  product_id: "87654321",
  supplier_name: "Authentic Supplier",
  unit_price_won: 1000,
  unit: "EA",
  spec_snapshot: "CCTV 4MP",
  source_url: "https://example.test/products/87654321",
  api_operation: "getProductInfo",
  observed_at: "2026-07-23T10:01:00+09:00",
  source_payload_sha256: HASH_B,
  authenticity: {
    kind: "captured_source_payload",
    source_payload_sha256: HASH_B
  },
  selection_evidence: {
    comparison_group: "cctv-4mp-camera",
    specification_fingerprint: HASH_C,
    eligible: true,
    auto_selected: false,
    lowest_observed_unit_price_won: 1000,
    compared_observation_ids: ["koreanet-native", "competitor-native"]
  }
};

function userQuote(
  quoteId: string,
  supplierName: string,
  unitPriceWon: string,
  specification: string,
  unit: string
) {
  return {
    kind: "user_quote",
    quoteId,
    supplierName,
    unitPriceWon,
    specification,
    unit,
    quoteDate: "2026-07-23",
    documentSha256: HASH_C
  } as const;
}

export async function mixedNativeInput() {
  const repository = await loadOfficialRepository();
  const market = repository.marketPrices.find((row) => row.material_included);
  const productivity = repository.productivity[0];
  if (market === undefined || productivity === undefined) {
    throw new TypeError("Pinned official fixture rows are missing");
  }
  const wagesByCode = new Map(repository.wages.map((wage) => [wage.job_code, wage]));
  const coefficients = Object.entries(productivity.coefficients_by_job_code).map(
    ([jobCode, coefficient]) => {
      const wage = wagesByCode.get(jobCode);
      if (wage === undefined) {
        throw new TypeError(`Pinned wage ${jobCode} is missing`);
      }
      return {
        jobCode,
        coefficient,
        dailyWageWon: String(wage.daily_wage_krw),
        wageSource: {
          datasetVersion: repository.revision.datasetVersion,
          compositeSha256: repository.revision.compositeSha256,
          sourceManifestSha256: repository.revision.sourceManifestSha256,
          sourceId: wage.source_id,
          sourceUrl: wage.source_url,
          sourcePdfSha256: wage.source_pdf_sha256,
          sourcePdfPages: wage.source_pdf_pages,
          effectiveFrom: wage.effective_from,
          jurisdiction: wage.jurisdiction
        }
      };
    }
  );
  const rateContext = {
    issuer: "내부 검토자",
    regime: "national",
    noticeOrContractDate: "2026-07-23",
    projectType: "CCTV/LAN/FIBER",
    contractLevel: "general",
    amountBasis: "재료비 참고",
    suppliedMaterials: "mixed",
    pricingMethod: "2026 official reference",
    vatStatus: "unknown",
    datasetVersion: repository.revision.datasetVersion,
    compositeSha256: repository.revision.compositeSha256,
    sourceManifestSha256: repository.revision.sourceManifestSha256
  } as const;
  const selection = selectKoreaNetCandidate({
    requestedItemKey: "cctv-4mp-camera",
    specification: "CCTV 4MP",
    unit: "EA",
    candidates: [koreaNet, competitor]
  });
  if (selection.kind !== "selected") {
    throw new TypeError("KoreaNet fixture must be selected");
  }

  return {
    projectId: "native-2026-sample",
    projectName: "2026 CCTV/LAN/FIBER 내부검토",
    preparedOn: "2026-07-23",
    lines: [
      {
        field: "CCTV",
        line: {
          id: "cctv-1",
          role: { kind: "main" },
          itemName: "4MP CCTV 카메라",
          specification: "CCTV 4MP",
          unit: "EA",
          quantity: "2",
          cost: {
            kind: "direct",
            provenance: {
              kind: "direct",
              observationId: koreaNet.observation_id,
              productId: koreaNet.product_id,
              supplierName: koreaNet.supplier_name,
              unitPriceWon: String(koreaNet.unit_price_won),
              specification: koreaNet.spec_snapshot,
              unit: koreaNet.unit,
              sourceUrl: koreaNet.source_url,
              apiOperation: koreaNet.api_operation,
              observedAt: koreaNet.observed_at,
              sourcePayloadSha256: koreaNet.source_payload_sha256
            }
          }
        }
      },
      {
        field: "LAN",
        line: {
          id: "lan-1",
          role: { kind: "main" },
          itemName: "사용자 견적 스위치",
          specification: "24PORT",
          unit: "EA",
          quantity: "3",
          cost: {
            kind: "direct",
            provenance: userQuote("user-lan", "사용자 입력", "2000", "24PORT", "EA")
          }
        }
      },
      {
        field: "FIBER",
        line: {
          id: "fiber-1",
          role: { kind: "main" },
          itemName: "광접속함",
          specification: "12CORE",
          unit: "EA",
          quantity: "1",
          cost: {
            kind: "three_company_min",
            quotes: [
              {
                slot: "A",
                provenance: userQuote("fiber-a", "A사", "500", "12CORE", "EA")
              },
              {
                slot: "B",
                provenance: userQuote("fiber-b", "B사", "500", "12CORE", "EA")
              },
              {
                slot: "C",
                provenance: userQuote("fiber-c", "C사", "700", "12CORE", "EA")
              }
            ]
          }
        }
      },
      {
        field: "LAN",
        line: {
          id: "lan-official",
          role: { kind: "main" },
          itemName: market.name,
          specification: market.specification,
          unit: market.unit,
          quantity: "1",
          cost: {
            kind: "market_price",
            provenance: {
              kind: "market_price",
              datasetVersion: repository.revision.datasetVersion,
              compositeSha256: repository.revision.compositeSha256,
              sourceManifestSha256: repository.revision.sourceManifestSha256,
              sourceId: market.source_id,
              sourceUrl: market.source_url,
              sourcePdfSha256: market.source_pdf_sha256,
              sourcePdfPages: [market.source_pdf_page],
              effectiveFrom: market.effective_from,
              jurisdiction: market.jurisdiction,
              workCode: market.work_code,
              specification: market.specification,
              unit: market.unit,
              materialIncluded: market.material_included,
              unitPriceWon: String(market.unit_price_krw)
            },
            rateContext
          }
        }
      },
      {
        field: "FIBER",
        line: {
          id: "fiber-official",
          role: { kind: "main" },
          itemName: productivity.task,
          specification: productivity.specification,
          unit: productivity.unit,
          quantity: "1",
          cost: {
            kind: "standard_quantity",
            provenance: {
              kind: "standard_quantity",
              datasetVersion: repository.revision.datasetVersion,
              compositeSha256: repository.revision.compositeSha256,
              sourceManifestSha256: repository.revision.sourceManifestSha256,
              sourceId: productivity.source_id,
              sourceUrl: productivity.source_url,
              sourcePdfSha256: productivity.source_pdf_sha256,
              sourcePdfPages: productivity.source_pdf_pages,
              effectiveFrom: productivity.effective_from,
              jurisdiction: productivity.jurisdiction,
              standardItem: productivity.standard_item,
              task: productivity.task,
              specification: productivity.specification,
              unit: productivity.unit,
              coefficients
            },
            rateContext
          }
        }
      }
    ],
    koreaNetSelections: [{ lineId: "cctv-1", result: selection }]
  } as const;
}
