export const SHA_A = "a".repeat(64);
export const SHA_B = "b".repeat(64);
export const SHA_C = "c".repeat(64);
export const OFFICIAL_COMPOSITE_SHA256 =
  "0705bbc698818fd1b291df2c554028253777e10503863fe2564830faf7e3fe16";
export const OFFICIAL_SOURCE_MANIFEST_SHA256 =
  "482309efcfd22ca0cc15dc55c3e08d9b1dc01ae6ef15187946ccdf53fc0f0745";

export const PROFILE_A = {
  id: "A",
  revision: "445012e259ab5318a1d52468cce93ee28a55a8bcb467876f40a47a939e4668db",
  capacity: 16,
  feePolicy: {
    kind: "fee_up",
    rate: "0.0054",
    incrementWon: "1000"
  }
};

export const PROFILE_B = {
  id: "B",
  revision: "2220cd9936ebdf908d64c0571a4c8de83973eaa89c6778a64afec07de7c5e701",
  capacity: 9,
  feePolicy: {
    kind: "total_up",
    rate: "0.0054",
    incrementWon: "1000"
  }
};

export const PROFILE_C = {
  id: "C",
  revision: "8a55700bdaf62a00c208c7286531fd56ca321571f73f7620505a823ef5d4d0f1",
  capacity: 24,
  feePolicy: {
    kind: "total_up",
    rate: "0.0054",
    incrementWon: "1000"
  }
};

export const DIRECT_SOURCE = {
  kind: "direct",
  observationId: "obs-20260723-1",
  productId: "12345678",
  supplierName: "검증 공급사",
  unitPriceWon: "1500",
  specification: "800만화소",
  unit: "대",
  sourceUrl: "https://example.test/products/12345678",
  apiOperation: "getMASCntrctPrdctInfoList",
  observedAt: "2026-07-23T09:00:00+09:00",
  sourcePayloadSha256: SHA_A
};

export const USER_QUOTE_A = {
  kind: "user_quote",
  quoteId: "quote-a",
  supplierName: "A 공급사",
  unitPriceWon: "1000",
  specification: "800만화소",
  unit: "대",
  quoteDate: "2026-07-20",
  documentSha256: SHA_A
};

export const USER_QUOTE_B = {
  kind: "user_quote",
  quoteId: "quote-b",
  supplierName: "B 공급사",
  unitPriceWon: "1000",
  specification: "800만화소",
  unit: "대",
  quoteDate: "2026-07-21",
  documentSha256: SHA_B
};

export const USER_QUOTE_C = {
  kind: "user_quote",
  quoteId: "quote-c",
  supplierName: "C 공급사",
  unitPriceWon: "1200",
  specification: "800만화소",
  unit: "대",
  quoteDate: "2026-07-22",
  documentSha256: SHA_C
};

export const BASE_LINE = {
  id: "line-1",
  role: { kind: "main" },
  itemName: "영상감시장치",
  specification: "800만화소",
  unit: "대",
  quantity: "2",
  cost: {
    kind: "direct",
    provenance: DIRECT_SOURCE
  }
};

export const BASE_ESTIMATE = {
  id: "estimate-1",
  revision: 1,
  profile: PROFILE_B,
  lines: [BASE_LINE]
};

export const RATE_CONTEXT = {
  issuer: "한국정보통신산업연구원",
  regime: "national",
  noticeOrContractDate: "2026-07-23",
  projectType: "CCTV",
  contractLevel: "general",
  amountBasis: "unit-price",
  suppliedMaterials: "included",
  pricingMethod: "official-market-price",
  vatStatus: "excluded",
  datasetVersion: "2026-H2-KR-CCTV-LAN-FIBER-v1",
  compositeSha256: OFFICIAL_COMPOSITE_SHA256,
  sourceManifestSha256: OFFICIAL_SOURCE_MANIFEST_SHA256
};

export const MARKET_PRICE_SOURCE = {
  kind: "market_price",
  datasetVersion: RATE_CONTEXT.datasetVersion,
  compositeSha256: RATE_CONTEXT.compositeSha256,
  sourceManifestSha256: RATE_CONTEXT.sourceManifestSha256,
  sourceId: "KICI_2026_H2_MARKET_PRICE",
  sourceUrl: "https://www.kici.re.kr/page/support/view.html?board_id=price_library&post_id=67009",
  sourcePdfSha256: SHA_B,
  sourcePdfPages: [69],
  effectiveFrom: "2026-07-01",
  jurisdiction: "KR_NATIONWIDE",
  workCode: "DA1420102",
  specification: "SMF 2C, 구내",
  unit: "m",
  materialIncluded: true,
  unitPriceWon: "6251"
};

export const PRODUCTIVITY_SOURCE = {
  kind: "standard_quantity",
  datasetVersion: RATE_CONTEXT.datasetVersion,
  compositeSha256: RATE_CONTEXT.compositeSha256,
  sourceManifestSha256: RATE_CONTEXT.sourceManifestSha256,
  sourceId: "KICI_2026_STANDARD_PRODUCTIVITY",
  sourceUrl: "https://www.kici.re.kr/page/support/view.html?board_id=norm_library&post_id=2162",
  sourcePdfSha256: SHA_B,
  sourcePdfPages: [300],
  effectiveFrom: "2026-01-01",
  jurisdiction: "KR_NATIONWIDE",
  standardItem: "9-2-1-1",
  task: "카메라 설치",
  specification: "일반형",
  unit: "대",
  coefficients: [
    {
      jobCode: "1003",
      coefficient: "0.25",
      dailyWageWon: "1000",
      wageSource: {
        datasetVersion: RATE_CONTEXT.datasetVersion,
        compositeSha256: RATE_CONTEXT.compositeSha256,
        sourceManifestSha256: RATE_CONTEXT.sourceManifestSha256,
        sourceId: "CAK_2026_H1_WAGE",
        sourceUrl: "https://gwangju.cak.or.kr/download.do?uuid=test",
        sourcePdfSha256: SHA_C,
        sourcePdfPages: [10],
        effectiveFrom: "2026-01-01",
        jurisdiction: "KR_NATIONWIDE"
      }
    },
    {
      jobCode: "1087",
      coefficient: "0.5",
      dailyWageWon: "2000",
      wageSource: {
        datasetVersion: RATE_CONTEXT.datasetVersion,
        compositeSha256: RATE_CONTEXT.compositeSha256,
        sourceManifestSha256: RATE_CONTEXT.sourceManifestSha256,
        sourceId: "CAK_2026_H1_WAGE",
        sourceUrl: "https://gwangju.cak.or.kr/download.do?uuid=test",
        sourcePdfSha256: SHA_C,
        sourcePdfPages: [12],
        effectiveFrom: "2026-01-01",
        jurisdiction: "KR_NATIONWIDE"
      }
    }
  ]
};
