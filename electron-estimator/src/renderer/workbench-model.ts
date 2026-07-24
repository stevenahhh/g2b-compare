import type { EstimateLine } from "../shared/contracts.js";
import type {
  KoreaNetSelectionReason,
  KoreaNetSelectionResult
} from "../official/selector.js";
import type { SourcedProductObservation } from "../official/schemas.js";

export type Density = "compact" | "regular" | "comfortable";
export type CostMethod = EstimateLine["cost"]["kind"];

export type WorkbenchRow = {
  readonly id: string;
  itemName: string;
  specification: string;
  unit: string;
  quantity: string;
  unitPriceWon: number;
  readonly method: CostMethod;
  readonly source: SourcedProductObservation | null;
  readonly selection: KoreaNetSelectionResult | null;
};

const payloadHash = "a4".repeat(32);
const specificationHash = "b7".repeat(32);
const observedAt = "2026-07-23T09:30:00+09:00";
const sourceUrl =
  "https://shop.g2b.go.kr/example/products/88001234?operation=getProduct";

const locationEvidence = Object.freeze({
  statement: "공급자 사업장 소재지가 대한민국으로 확인됨.",
  source_url: sourceUrl,
  observed_at: observedAt,
  source_payload_sha256: payloadHash
});

const serviceEvidence = Object.freeze({
  statement: "요청 지역 납품 가능 범위가 원문 응답에 포함됨.",
  source_url: sourceUrl,
  observed_at: observedAt,
  source_payload_sha256: payloadHash
});

const koreaNet = Object.freeze({
  observation_id: "obs-koreanet-20260723",
  product_id: "88001234",
  supplier_name: "코리아넷",
  unit_price_won: 125_000,
  unit: "대",
  spec_snapshot: "5MP, H.265, PoE, 실외형",
  source_url: sourceUrl,
  api_operation: "getProductInfo",
  observed_at: observedAt,
  source_payload_sha256: payloadHash,
  authenticity: {
    kind: "captured_source_payload" as const,
    source_payload_sha256: payloadHash
  },
  supplier_location_evidence: locationEvidence,
  service_area_evidence: serviceEvidence,
  selection_evidence: {
    comparison_group: "CCTV-5MP-POE",
    specification_fingerprint: specificationHash,
    eligible: true,
    auto_selected: true,
    lowest_observed_unit_price_won: 125_000,
    compared_observation_ids: [
      "obs-koreanet-20260723",
      "obs-competitor-20260723"
    ]
  }
}) satisfies SourcedProductObservation;

const competitor = Object.freeze({
  observation_id: "obs-competitor-20260723",
  product_id: "88004567",
  supplier_name: "대한정보통신",
  unit_price_won: 118_000,
  unit: "m",
  spec_snapshot: "싱글모드 4코어, 옥외용",
  source_url: "https://shop.g2b.go.kr/example/products/88004567",
  api_operation: "getProductInfo",
  observed_at: observedAt,
  source_payload_sha256: payloadHash,
  authenticity: {
    kind: "captured_source_payload" as const,
    source_payload_sha256: payloadHash
  },
  selection_evidence: {
    comparison_group: "FIBER-SM-4C",
    specification_fingerprint: specificationHash,
    eligible: true,
    auto_selected: false,
    lowest_observed_unit_price_won: 118_000,
    compared_observation_ids: [
      "obs-competitor-20260723",
      "obs-koreanet-20260723"
    ]
  }
}) satisfies SourcedProductObservation;

const selectedKoreaNet = Object.freeze({
  kind: "selected",
  autoSelected: true,
  reason: "KOREANET_LOWEST",
  selected: koreaNet,
  lowestUnitPriceWon: koreaNet.unit_price_won,
  comparableCandidates: Object.freeze([koreaNet, competitor])
}) satisfies KoreaNetSelectionResult;

const lowerAuthentic = Object.freeze({
  kind: "not_selected",
  autoSelected: false,
  reason: "LOWER_AUTHENTIC_CANDIDATE",
  selected: null,
  lowestUnitPriceWon: competitor.unit_price_won,
  comparableCandidates: Object.freeze([competitor, koreaNet])
}) satisfies KoreaNetSelectionResult;

const extraItems = [
  "CAT.6 UTP 케이블",
  "24포트 PoE 스위치",
  "광분배함",
  "랙 캐비닛",
  "무정전 전원장치",
  "영상 저장장치",
  "모니터",
  "광컨버터",
  "접지 자재",
  "배관 자재",
  "표찰",
  "설치 인건비",
  "시험 및 조정",
  "운반비",
  "안전관리비",
  "준공 도서",
  "통합 배선 시험",
  "장비 설정",
  "현장 교육",
  "예비 자재",
  "케이블 트레이",
  "광접속함",
  "서지 보호기",
  "라벨 프린트",
  "회선 성능 측정",
  "준공 청소"
] as const;

export function createWorkbenchRows(): WorkbenchRow[] {
  const rows: WorkbenchRow[] = [
    {
      id: "line-koreanet",
      itemName: "네트워크 카메라",
      specification: koreaNet.spec_snapshot,
      unit: koreaNet.unit,
      quantity: "12",
      unitPriceWon: koreaNet.unit_price_won,
      method: "direct",
      source: koreaNet,
      selection: selectedKoreaNet
    },
    {
      id: "line-lower-authentic",
      itemName: "광케이블",
      specification: competitor.spec_snapshot,
      unit: competitor.unit,
      quantity: "180",
      unitPriceWon: competitor.unit_price_won,
      method: "three_company_min",
      source: competitor,
      selection: lowerAuthentic
    },
    {
      id: "line-empty-source",
      itemName: "현장 정리",
      specification: "작업 후 정리 및 반출",
      unit: "식",
      quantity: "1",
      unitPriceWon: 230_000,
      method: "direct",
      source: null,
      selection: null
    }
  ];
  extraItems.forEach((itemName, index) => {
    rows.push({
      id: `line-extra-${String(index + 1)}`,
      itemName,
      specification: "프로젝트 기준 규격",
      unit: index % 2 === 0 ? "m" : "식",
      quantity: String(index + 1),
      unitPriceWon: 18_500 + index * 2_750,
      method: index % 3 === 0 ? "market_price" : "direct",
      source: null,
      selection: null
    });
  });
  return rows;
}

export const SELECTION_REASON_LABELS = {
  KOREANET_LOWEST: "조건 충족 최저가",
  KOREANET_NOT_AVAILABLE: "KoreaNet 후보 없음",
  KOREANET_TIED_LOWEST: "조건 충족 공동최저가",
  LOWER_AUTHENTIC_CANDIDATE: "더 낮은 실제 후보가 있어 자동선택하지 않음",
  NO_COMPARABLE_CANDIDATE: "비교 가능한 후보 부족",
  SOURCE_EVIDENCE_INCOMPLETE: "출처 근거 불완전",
  SPECIFICATION_MISMATCH: "규격 불일치",
  UNIT_MISMATCH: "단위 불일치"
} as const satisfies Record<KoreaNetSelectionReason, string>;
