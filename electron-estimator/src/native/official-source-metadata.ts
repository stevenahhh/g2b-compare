const OFFICIAL_DOCUMENTS = {
  CAK_2026_H1_WAGE: {
    licenseId: "SOURCE_TERMS_NOT_ESTABLISHED",
    title: "2026년 상반기 적용 건설업 임금실태 조사 보고서"
  },
  KICI_2026_H2_MARKET_PRICE: {
    licenseId: "KOGL-TYPE-4",
    title: "2026년도 하반기 적용 정보통신공사 표준시장단가"
  },
  KICI_2026_STANDARD_PRODUCTIVITY: {
    licenseId: "KOGL-TYPE-4",
    title: "2026년 적용 정보통신공사 표준품셈"
  }
} as const;

export function officialDocument(sourceId: string): {
  readonly licenseId: string;
  readonly title: string;
} {
  switch (sourceId) {
    case "KICI_2026_STANDARD_PRODUCTIVITY":
      return OFFICIAL_DOCUMENTS.KICI_2026_STANDARD_PRODUCTIVITY;
    case "KICI_2026_H2_MARKET_PRICE":
      return OFFICIAL_DOCUMENTS.KICI_2026_H2_MARKET_PRICE;
    case "CAK_2026_H1_WAGE":
      return OFFICIAL_DOCUMENTS.CAK_2026_H1_WAGE;
    default:
      throw new TypeError(`Unexpected official source: ${sourceId}`);
  }
}
