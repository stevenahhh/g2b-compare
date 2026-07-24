import { element } from "../../renderer/dom.js";
import type {
  NativeDraftRow,
  QuoteSlot,
  UserQuoteDraft
} from "./state.js";
import { textField } from "./view-fields.js";
import type { NativeViewOptions } from "./view-types.js";

export function createSourceEditor(
  options: NativeViewOptions,
  row: NativeDraftRow
): HTMLElement {
  switch (row.method) {
    case "direct":
      return directEditor(options, row);
    case "three_company_min":
      return threeCompanyEditor(options, row);
    case "market_price":
    case "standard_quantity":
      return element("section", {
        className: "source-editor",
        children: [
          element("h3", { text: "공식 출처" }),
          element("p", {
            text: row.method === "market_price"
              ? row.market?.name ?? "시장단가를 카탈로그에서 선택해야 함."
              : row.productivity?.task ?? "표준품셈을 카탈로그에서 선택해야 함."
          })
        ]
      });
    default:
      return assertNever(row.method);
  }
}

function directEditor(
  options: NativeViewOptions,
  row: NativeDraftRow
): HTMLElement {
  const sourceKind = element("select", {
    attributes: {
      "data-testid": "source-kind",
      "aria-label": "직접단가 출처 종류"
    },
    children: [
      element("option", {
        text: "사용자 입력 단가 · 미검증",
        attributes: { value: "user_quote" }
      }),
      element("option", {
        text: "조달 관측 후보",
        attributes: { value: "sourced_observation" }
      })
    ]
  });
  sourceKind.value = row.sourceKind;
  sourceKind.addEventListener("change", () => {
    row.sourceKind =
      sourceKind.value === "sourced_observation"
        ? "sourced_observation"
        : "user_quote";
    options.events.rerender();
  });
  const section = element("section", {
    className: "source-editor",
    attributes: { "data-testid": "source-editor" },
    children: [element("h3", { text: "직접단가 출처" }), sourceKind]
  });
  if (row.sourceKind === "user_quote") {
    section.append(quoteFields(row.directQuote, "", options.events.updateDerived));
    return section;
  }
  const run = element("button", {
    className: "button button-primary",
    text: "Task8 후보 판정",
    attributes: { type: "button", "data-testid": "run-selector" }
  });
  run.addEventListener("click", () => {
    void options.events.runSelector(row);
  });
  section.append(
    textField(
      "비교 그룹",
      "comparison-group",
      {
        value: row.comparisonGroup,
        set: (value) => {
          row.comparisonGroup = value;
        }
      },
      options.events.updateDerived
    ),
    element("p", {
      text: "검증된 메인 저장소의 관측 후보만 판정에 사용함."
    }),
    run
  );
  return section;
}

function threeCompanyEditor(
  options: NativeViewOptions,
  row: NativeDraftRow
): HTMLElement {
  return element("section", {
    className: "source-editor",
    children: [
      element("h3", { text: "3사 견적 출처 · 미검증" }),
      ...(["A", "B", "C"] as const).map((slot) =>
        quoteFields(row.quotes[slot], slot, options.events.updateDerived)
      )
    ]
  });
}

function quoteFields(
  quote: UserQuoteDraft,
  slot: "" | QuoteSlot,
  update: () => void
): HTMLElement {
  const prefix = slot.length === 0 ? "" : `quote-${slot}-`;
  return element("fieldset", {
    className: "quote-fields",
    children: [
      element("legend", { text: slot.length === 0 ? "사용자 입력 단가 · 미검증" : `${slot}사 · 미검증` }),
      textField("견적 ID", `${prefix}${slot.length === 0 ? "quote-id" : "id"}`, binding(quote, "quoteId"), update),
      textField("업체", `${prefix}${slot.length === 0 ? "supplier-name" : "supplier"}`, binding(quote, "supplierName"), update),
      textField("단가", `${prefix}${slot.length === 0 ? "source-unit-price" : "price"}`, binding(quote, "unitPriceWon"), update),
      textField("견적일", `${prefix}${slot.length === 0 ? "quote-date" : "date"}`, binding(quote, "quoteDate"), update, "date"),
      textField("문서 SHA-256", `${prefix}${slot.length === 0 ? "document-sha256" : "sha"}`, binding(quote, "documentSha256"), update)
    ]
  });
}

function binding(
  quote: UserQuoteDraft,
  key: keyof UserQuoteDraft
): { readonly value: string; readonly set: (value: string) => void } {
  return {
    value: quote[key],
    set: (value) => {
      quote[key] = value;
    }
  };
}

function assertNever(value: never): never {
  throw new TypeError(`Unexpected method: ${String(value)}`);
}
