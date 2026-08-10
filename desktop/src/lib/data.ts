import type { DataStatus, DataSyncStage } from "./models";

export const DATA_COUNTS: ReadonlyArray<readonly [string, keyof DataStatus]> = [
  ["업체", "company_count"],
  ["주품목", "product_count"],
  ["관계", "relation_count"],
  ["옵션 행", "option_row_count"],
  ["고유 옵션", "unique_option_count"],
  ["API 수집 대기", "pending_api_target_count"],
  ["사이트 수집 대기", "pending_site_product_count"],
];

const SYNC_STAGE_LABELS: Record<DataSyncStage, string> = {
  sync: "공식 API 동기화",
  "import-relations": "관계 가져오기",
  materialize: "데이터 구성",
  "rebuild-index": "검색 색인 재구성",
  precompute: "비교군 사전 계산",
};

export function syncStageLabel(stage: DataSyncStage | null): string {
  return stage ? SYNC_STAGE_LABELS[stage] : "마무리";
}

export function safeDiagnosticMessage(caught: unknown): string {
  const raw = typeof caught === "string"
    ? caught
    : caught && typeof caught === "object" && "code" in caught
      ? String((caught as { code: unknown }).code)
      : caught instanceof Error
        ? caught.message
        : "";

  if (/^HTTP\s+[1-5]\d\d$/i.test(raw.trim())) {
    return `공식 데이터 요청 실패 · ${raw.trim().toUpperCase()}`;
  }
  if (/data-unavailable/i.test(raw)) {
    return "로컬 데이터 상태를 확인할 수 없습니다.";
  }
  if (/offline|transport-unavailable/i.test(raw)) {
    return "네트워크 연결이 없어 작업을 완료하지 못했습니다.";
  }
  return "데이터 작업을 완료하지 못했습니다. 잠시 후 다시 시도하세요.";
}
