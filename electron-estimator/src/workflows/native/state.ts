import type {
  MarketPriceRow,
  ProductivityRow,
  SourcedProductObservation
} from "../../official/schemas.js";
import type {
  NativeCatalog,
  NativeSelectionResult
} from "./contracts.js";

export type NativeField = "CCTV" | "LAN" | "FIBER";
export type NativeCostMethod =
  | "direct"
  | "three_company_min"
  | "market_price"
  | "standard_quantity";
export type DirectSourceKind = "user_quote" | "sourced_observation";
export type QuoteSlot = "A" | "B" | "C";

export type UserQuoteDraft = {
  quoteId: string;
  supplierName: string;
  unitPriceWon: string;
  quoteDate: string;
  documentSha256: string;
};

export type NativeDraftRow = {
  readonly id: string;
  field: NativeField;
  itemName: string;
  specification: string;
  unit: string;
  quantity: string;
  method: NativeCostMethod;
  sourceKind: DirectSourceKind;
  readonly directQuote: UserQuoteDraft;
  readonly quotes: Record<QuoteSlot, UserQuoteDraft>;
  observation: SourcedProductObservation | null;
  selection: NativeSelectionResult | null;
  market: MarketPriceRow | null;
  productivity: ProductivityRow | null;
  comparisonGroup: string;
};

export type RateContextDraft = {
  issuer: string;
  regime: "" | "national" | "local";
  noticeOrContractDate: string;
  projectType: string;
  contractLevel: "" | "general" | "subcontract";
  amountBasis: string;
  suppliedMaterials: "" | "included" | "excluded" | "mixed";
  pricingMethod: string;
  vatStatus: "" | "included" | "excluded" | "unknown";
};

export type NativeWorkflowState = {
  projectId: string;
  projectName: string;
  preparedOn: string;
  readonly rateContext: RateContextDraft;
  readonly rows: NativeDraftRow[];
  selectedId: string;
  nextRow: number;
  catalog: NativeCatalog | null;
  catalogQuery: string;
  status: string;
  exporting: boolean;
  inspectorOpen: boolean;
};

function emptyQuote(): UserQuoteDraft {
  return {
    quoteId: "",
    supplierName: "",
    unitPriceWon: "",
    quoteDate: "",
    documentSha256: ""
  };
}

export function createNativeWorkflowState(): NativeWorkflowState {
  return {
    projectId: "",
    projectName: "",
    preparedOn: "",
    rateContext: {
      issuer: "",
      regime: "",
      noticeOrContractDate: "",
      projectType: "",
      contractLevel: "",
      amountBasis: "",
      suppliedMaterials: "",
      pricingMethod: "",
      vatStatus: ""
    },
    rows: [],
    selectedId: "",
    nextRow: 1,
    catalog: null,
    catalogQuery: "",
    status: "공식 카탈로그를 불러오는 중임.",
    exporting: false,
    inspectorOpen: false
  };
}

export function addDraftRow(
  state: NativeWorkflowState,
  field: NativeField = "CCTV"
): NativeDraftRow {
  const row: NativeDraftRow = {
    id: `line-${String(state.nextRow)}`,
    field,
    itemName: "",
    specification: "",
    unit: "",
    quantity: "1",
    method: "direct",
    sourceKind: "user_quote",
    directQuote: emptyQuote(),
    quotes: {
      A: emptyQuote(),
      B: emptyQuote(),
      C: emptyQuote()
    },
    observation: null,
    selection: null,
    market: null,
    productivity: null,
    comparisonGroup: ""
  };
  state.nextRow += 1;
  state.rows.push(row);
  state.selectedId = row.id;
  return row;
}

export function selectedDraftRow(
  state: NativeWorkflowState
): NativeDraftRow | null {
  return state.rows.find((row) => row.id === state.selectedId) ?? null;
}

export function normalizeField(category: string): NativeField {
  return category === "광케이블" ? "FIBER" : category === "LAN" ? "LAN" : "CCTV";
}
