import type { NativeProjectWire } from "./contracts.js";
import type {
  NativeDraftRow,
  NativeWorkflowState,
  UserQuoteDraft
} from "./state.js";
import type { NativeErrorCode } from "./validation.js";
import { marketCost, productivityCost } from "./validation-official.js";

type WireLine = NativeProjectWire["lines"][number];

export function buildWireLine(
  state: NativeWorkflowState,
  row: NativeDraftRow,
  codes: Set<NativeErrorCode>
): WireLine["line"] | null {
  if (
    row.itemName.trim().length === 0 ||
    row.specification.trim().length === 0 ||
    row.unit.trim().length === 0
  ) {
    codes.add("REQUIRED_FIELD");
  }
  if (!positive(row.quantity)) {
    codes.add("NON_POSITIVE_INPUT");
  }
  if (row.market !== null && row.productivity !== null) {
    codes.add("PRICING_METHOD_CONFLICT");
  }
  const cost = buildCost(state, row, codes);
  if (cost === null) {
    return null;
  }
  return {
    id: row.id,
    role: { kind: "main" },
    itemName: row.itemName,
    specification: row.specification,
    unit: row.unit,
    quantity: row.quantity,
    cost
  };
}

function buildCost(
  state: NativeWorkflowState,
  row: NativeDraftRow,
  codes: Set<NativeErrorCode>
): Readonly<Record<string, unknown>> | null {
  switch (row.method) {
    case "direct":
      return directCost(row, codes);
    case "three_company_min":
      return threeCompanyCost(row, codes);
    case "market_price":
      return marketCost(state, row, codes);
    case "standard_quantity":
      return productivityCost(state, row, codes);
    default:
      return assertNever(row.method);
  }
}

function directCost(
  row: NativeDraftRow,
  codes: Set<NativeErrorCode>
): Readonly<Record<string, unknown>> | null {
  if (row.sourceKind === "sourced_observation") {
    const source = row.observation;
    if (source === null) {
      codes.add("SOURCE_REQUIRED");
      return null;
    }
    if (
      row.selection !== null &&
      (source.spec_snapshot !== row.specification || source.unit !== row.unit)
    ) {
      codes.add("STALE_SELECTOR");
    }
    return {
      kind: "direct",
      provenance: {
        kind: "direct",
        observationId: source.observation_id,
        productId: source.product_id,
        supplierName: source.supplier_name,
        unitPriceWon: String(source.unit_price_won),
        specification: source.spec_snapshot,
        unit: source.unit,
        sourceUrl: source.source_url,
        apiOperation: source.api_operation,
        observedAt: source.observed_at,
        sourcePayloadSha256: source.source_payload_sha256
      }
    };
  }
  const provenance = userQuote(row.directQuote, row, codes);
  return provenance === null ? null : { kind: "direct", provenance };
}

function threeCompanyCost(
  row: NativeDraftRow,
  codes: Set<NativeErrorCode>
): Readonly<Record<string, unknown>> | null {
  const quotes = (["A", "B", "C"] as const).map((slot) => {
    const provenance = userQuote(row.quotes[slot], row, codes);
    return provenance === null ? null : { slot, provenance };
  });
  return quotes.some((quote) => quote === null)
    ? null
    : { kind: "three_company_min", quotes };
}

function userQuote(
  quote: UserQuoteDraft,
  row: NativeDraftRow,
  codes: Set<NativeErrorCode>
): Readonly<Record<string, unknown>> | null {
  const sourceMissing =
    quote.quoteId.trim().length === 0 ||
    quote.supplierName.trim().length === 0 ||
    quote.quoteDate.length === 0 ||
    !/^[0-9a-f]{64}$/u.test(quote.documentSha256);
  if (sourceMissing) {
    codes.add("SOURCE_REQUIRED");
  }
  if (!positive(quote.unitPriceWon)) {
    codes.add("NON_POSITIVE_INPUT");
  }
  if (sourceMissing || !positive(quote.unitPriceWon)) {
    return null;
  }
  return {
    kind: "user_quote",
    quoteId: quote.quoteId,
    supplierName: quote.supplierName,
    unitPriceWon: quote.unitPriceWon,
    specification: row.specification,
    unit: row.unit,
    quoteDate: quote.quoteDate,
    documentSha256: quote.documentSha256
  };
}

function positive(value: string): boolean {
  const number = Number(value.replaceAll(",", ""));
  return Number.isFinite(number) && number > 0;
}

function assertNever(value: never): never {
  throw new TypeError(`Unexpected native method: ${String(value)}`);
}
