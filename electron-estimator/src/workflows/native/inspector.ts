import type { NativeLineCalculation } from "../../native/calculation.js";
import type { NativeDraftRow } from "./state.js";

export type InspectorDefinition = {
  readonly label: string;
  readonly value: string;
  readonly kind: "provenance" | "evidence";
};

export type NativeInspectorDto = {
  readonly method: string;
  readonly selectedSupplier: string;
  readonly formulaContribution: string;
  readonly definitions: readonly InspectorDefinition[];
  readonly selectorDto: string;
  readonly koreaNetSelected: boolean;
  readonly selectionReason: string;
};

const NUMBER = new Intl.NumberFormat("ko-KR");

export const SELECTION_REASON_LABELS = {
  KOREANET_LOWEST: "조건 충족 최저가",
  KOREANET_NOT_AVAILABLE: "KoreaNet 후보 없음",
  KOREANET_TIED_LOWEST: "조건 충족 공동최저가",
  LOWER_AUTHENTIC_CANDIDATE: "더 낮은 실제 후보가 있어 자동선택하지 않음",
  NO_COMPARABLE_CANDIDATE: "비교 가능한 후보 부족",
  SOURCE_EVIDENCE_INCOMPLETE: "출처 근거 불완전",
  SPECIFICATION_MISMATCH: "규격 불일치",
  UNIT_MISMATCH: "단위 불일치"
} as const;

export function createNativeInspectorDto(
  row: NativeDraftRow,
  calculation: NativeLineCalculation | undefined
): NativeInspectorDto {
  const unitPrice = calculation?.unitPriceWon.toNumber() ?? estimatedPrice(row);
  const amount = calculation?.amountWon.toNumber() ??
    unitPrice * (Number(row.quantity) || 0);
  return {
    method: row.method,
    selectedSupplier: supplier(row),
    formulaContribution: `${row.quantity || "0"} × ${NUMBER.format(unitPrice)}원 = ${NUMBER.format(amount)}원`,
    definitions: definitions(row),
    selectorDto: row.selection === null ? "" : JSON.stringify(row.selection),
    koreaNetSelected: row.selection?.kind === "selected",
    selectionReason:
      row.selection === null
        ? "자동선택 판정 없음"
        : SELECTION_REASON_LABELS[row.selection.reason]
  };
}

function definitions(row: NativeDraftRow): readonly InspectorDefinition[] {
  if (row.observation !== null) {
    const source = row.observation;
    return [
      definition("제품 ID", source.product_id),
      definition("업체", source.supplier_name),
      definition("단가", `${NUMBER.format(source.unit_price_won)}원`),
      definition("단위", source.unit),
      definition("규격 snapshot", source.spec_snapshot),
      definition("Source URL", source.source_url),
      definition("API operation", source.api_operation),
      definition("Observed time", source.observed_at),
      definition("Payload SHA-256", source.source_payload_sha256),
      evidence(
        "Supplier location evidence",
        source.supplier_location_evidence?.statement ?? "확인된 근거 없음"
      ),
      evidence(
        "Service area evidence",
        source.service_area_evidence?.statement ?? "확인된 근거 없음"
      )
    ];
  }
  if (row.market !== null) {
    const market = row.market;
    return officialDefinitions({
      sourceId: market.source_id,
      sourceUrl: market.source_url,
      pdfSha256: market.source_pdf_sha256,
      pages: String(market.source_pdf_page),
      effectiveFrom: market.effective_from,
      licenseId: market.license_id
    });
  }
  if (row.productivity !== null) {
    const productivity = row.productivity;
    return officialDefinitions({
      sourceId: productivity.source_id,
      sourceUrl: productivity.source_url,
      pdfSha256: productivity.source_pdf_sha256,
      pages: productivity.source_pdf_pages.join(", "),
      effectiveFrom: productivity.effective_from,
      licenseId: productivity.license_id
    });
  }
  if (row.method === "three_company_min") {
    return (["A", "B", "C"] as const).flatMap((slot) => [
      definition(`${slot}사`, row.quotes[slot].supplierName || "미입력"),
      definition(
        `${slot}사 단가`,
        row.quotes[slot].unitPriceWon || "미입력"
      )
    ]);
  }
  return [
    definition("사용자 견적 ID", row.directQuote.quoteId || "미입력"),
    definition("업체", row.directQuote.supplierName || "미입력"),
    definition("문서 SHA-256", row.directQuote.documentSha256 || "미입력")
  ];
}

function officialDefinitions(source: {
  readonly sourceId: string;
  readonly sourceUrl: string;
  readonly pdfSha256: string;
  readonly pages: string;
  readonly effectiveFrom: string;
  readonly licenseId: string;
}): readonly InspectorDefinition[] {
  return [
    definition("Source ID", source.sourceId),
    definition("Source URL", source.sourceUrl),
    definition("Effective from", source.effectiveFrom),
    definition("License", source.licenseId),
    definition("PDF pages", source.pages),
    definition("PDF SHA-256", source.pdfSha256)
  ];
}

function supplier(row: NativeDraftRow): string {
  if (row.observation !== null) {
    return row.observation.supplier_name;
  }
  if (row.method === "direct") {
    return row.directQuote.supplierName || "미입력";
  }
  return row.method === "three_company_min" ? "3사 비교" : "공식 자료";
}

function estimatedPrice(row: NativeDraftRow): number {
  if (row.observation !== null) {
    return row.observation.unit_price_won;
  }
  if (row.market !== null) {
    return row.market.unit_price_krw;
  }
  if (row.method === "three_company_min") {
    const values = Object.values(row.quotes)
      .map((quote) => Number(quote.unitPriceWon))
      .filter((value) => value > 0);
    return values.length === 0 ? 0 : Math.min(...values);
  }
  return Number(row.directQuote.unitPriceWon) || 0;
}

function definition(label: string, value: string): InspectorDefinition {
  return { label, value, kind: "provenance" };
}

function evidence(label: string, value: string): InspectorDefinition {
  return { label, value, kind: "evidence" };
}
