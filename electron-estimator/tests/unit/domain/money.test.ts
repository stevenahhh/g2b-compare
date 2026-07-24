import { describe, expect, test } from "vitest";
import {
  calculateProfileTotal,
  parseNonnegativeDecimal,
  parsePositiveWon,
  parseRate,
  selectThreeCompanyMinimum
} from "../../../src/domain/money.js";

describe("strict Decimal money", () => {
  test("B profile exact oracle and A-B-C tie", () => {
    // Given
    const subtotalWon = parseNonnegativeDecimal("20174460");
    const feeRate = parseRate("0.0054");
    const incrementWon = parsePositiveWon("1000");
    const quotes = [
      { slot: "A", quoteId: "quote-a", unitPriceWon: parsePositiveWon("1000") },
      { slot: "B", quoteId: "quote-b", unitPriceWon: parsePositiveWon("1000") },
      { slot: "C", quoteId: "quote-c", unitPriceWon: parsePositiveWon("1200") }
    ] as const;

    // When
    const total = calculateProfileTotal({
      subtotalWon,
      feePolicy: { kind: "total_up", rate: feeRate, incrementWon }
    });
    const selected = selectThreeCompanyMinimum(quotes);

    // Then
    expect(total.kind).toBe("total_up");
    expect(total.rawFeeWon.toString()).toBe("108942.084");
    if (total.kind === "total_up") {
      expect(total.unroundedTotalWon.toString()).toBe("20283402.084");
    }
    expect(total.totalWon.toFixed(0)).toBe("20284000");
    expect(selected.slot).toBe("A");
    expect(selected.quoteId).toBe("quote-a");
  });

  test("A and C profile totals match independent manifest oracles", () => {
    // Given
    const feeRate = parseRate("0.0054");
    const incrementWon = parsePositiveWon("1000");

    // When
    const a = calculateProfileTotal({
      subtotalWon: parseNonnegativeDecimal("38938530"),
      feePolicy: { kind: "fee_up", rate: feeRate, incrementWon }
    });
    const c = calculateProfileTotal({
      subtotalWon: parseNonnegativeDecimal("65499660"),
      feePolicy: { kind: "total_up", rate: feeRate, incrementWon }
    });

    // Then
    expect(a.kind).toBe("fee_up");
    if (a.kind === "fee_up") {
      expect(a.rawFeeWon.toString()).toBe("210268.062");
      expect(a.roundedFeeWon.toFixed(0)).toBe("211000");
      expect(a.totalWon.toFixed(0)).toBe("39149530");
    }
    expect(c.rawFeeWon.toString()).toBe("353698.164");
    expect(c.totalWon.toFixed(0)).toBe("65854000");
  });

  test.each(["1e3", " 1000", "+1000", "0x10", "1_000", "NaN", "Infinity", "1.5"])(
    "rejects unsafe integer-Won lexeme %s",
    (lexeme) => {
      // Given / When / Then
      expect(() => parsePositiveWon(lexeme)).toThrow();
    }
  );

  test("repeats the Decimal oracle deterministically", () => {
    // Given
    const input = {
      subtotalWon: parseNonnegativeDecimal("20174460"),
      feePolicy: {
        kind: "total_up",
        rate: parseRate("0.0054"),
        incrementWon: parsePositiveWon("1000")
      }
    } as const;

    // When
    const outputs = Array.from({ length: 100 }, () => {
      const result = calculateProfileTotal(input);
      return `${result.rawFeeWon.toString()}:${result.totalWon.toFixed(0)}`;
    });

    // Then
    expect(new Set(outputs)).toEqual(new Set(["108942.084:20284000"]));
  });
});
