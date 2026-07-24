import Decimal from "decimal.js";
import { selectThreeCompanyMinimum } from "../domain/money.js";
import { quoteSourceIdentity } from "../domain/provenance.js";
import type { EstimateLine } from "../domain/estimate.js";
import type { NativeWorkbookInput } from "./input.js";

export const REFERENCE_FEE_RATE = new Decimal("0.0054");
export const ROUNDING_INCREMENT_WON = new Decimal("1000");

export type NativeLineCalculation = {
  readonly lineId: string;
  readonly selectedSlot: "A" | "B" | "C" | "공식" | "직접";
  readonly unitPriceWon: Decimal;
  readonly amountWon: Decimal;
};

export type NativeCalculation = {
  readonly lines: readonly NativeLineCalculation[];
  readonly subtotalWon: Decimal;
  readonly referenceFeeWon: Decimal;
  readonly unroundedTotalWon: Decimal;
  readonly roundingAdjustmentWon: Decimal;
  readonly roundedTotalWon: Decimal;
  readonly fieldSubtotals: Readonly<Record<"CCTV" | "LAN" | "FIBER", Decimal>>;
};

export function calculateNativeWorkbook(
  input: NativeWorkbookInput
): NativeCalculation {
  const lines = input.lines.map((entry) => calculateLine(entry.line));
  const subtotalWon = lines.reduce(
    (total, line) => total.plus(line.amountWon),
    new Decimal(0)
  );
  const referenceFeeWon = subtotalWon.times(REFERENCE_FEE_RATE);
  const unroundedTotalWon = subtotalWon.plus(referenceFeeWon);
  const roundedTotalWon = unroundedTotalWon
    .dividedBy(ROUNDING_INCREMENT_WON)
    .ceil()
    .times(ROUNDING_INCREMENT_WON);
  const fieldSubtotals = {
    CCTV: fieldSubtotal(input, lines, "CCTV"),
    LAN: fieldSubtotal(input, lines, "LAN"),
    FIBER: fieldSubtotal(input, lines, "FIBER")
  } as const;
  return {
    lines,
    subtotalWon,
    referenceFeeWon,
    unroundedTotalWon,
    roundingAdjustmentWon: roundedTotalWon.minus(unroundedTotalWon),
    roundedTotalWon,
    fieldSubtotals
  };
}

function calculateLine(line: EstimateLine): NativeLineCalculation {
  switch (line.cost.kind) {
    case "direct":
      return lineCalculation(
        line,
        "직접",
        line.cost.provenance.unitPriceWon
      );
    case "three_company_min": {
      const [a, b, c] = line.cost.quotes;
      const selected = selectThreeCompanyMinimum(
        [
          { slot: a.slot, ...quoteSourceIdentity(a.provenance) },
          { slot: b.slot, ...quoteSourceIdentity(b.provenance) },
          { slot: c.slot, ...quoteSourceIdentity(c.provenance) }
        ]
      );
      return lineCalculation(line, selected.slot, selected.unitPriceWon);
    }
    case "market_price":
      return lineCalculation(
        line,
        "공식",
        line.cost.provenance.unitPriceWon
      );
    case "standard_quantity":
      return lineCalculation(
        line,
        "공식",
        line.cost.provenance.coefficients.reduce(
          (total, coefficient) =>
            total.plus(coefficient.coefficient.times(coefficient.dailyWageWon)),
          new Decimal(0)
        )
      );
    default:
      return assertNever(line.cost);
  }
}

function lineCalculation(
  line: EstimateLine,
  selectedSlot: NativeLineCalculation["selectedSlot"],
  unitPriceWon: Decimal
): NativeLineCalculation {
  return {
    lineId: line.id,
    selectedSlot,
    unitPriceWon,
    amountWon: unitPriceWon.times(line.quantity)
  };
}

function fieldSubtotal(
  input: NativeWorkbookInput,
  calculations: readonly NativeLineCalculation[],
  field: "CCTV" | "LAN" | "FIBER"
): Decimal {
  return input.lines.reduce(
    (total, entry, index) =>
      entry.field === field
        ? total.plus(calculations[index]?.amountWon ?? 0)
        : total,
    new Decimal(0)
  );
}

function assertNever(value: never): never {
  throw new TypeError(`Unexpected native cost method: ${String(value)}`);
}
