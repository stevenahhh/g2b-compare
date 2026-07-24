import { element } from "../../renderer/dom.js";
import type { NativeDraftRow, NativeField } from "./state.js";
import { bindComposingText } from "./view-fields.js";
import type { NativeViewOptions } from "./view-types.js";

export function createEstimateTable(options: NativeViewOptions): HTMLElement {
  const table = element("table", {
    className: "estimate-table native-estimate-table",
    attributes: { "aria-label": "네이티브 견적 편집 표" }
  });
  table.append(createHeader());
  const body = element("tbody");
  options.state.rows.forEach((row, index) => {
    body.append(createRow(options, row, index));
  });
  if (options.state.rows.length === 0) {
    body.append(
      element("tr", {
        children: [
          element("td", {
            className: "empty-table",
            text: "빈 행 추가 또는 공식 카탈로그 선택으로 시작함.",
            attributes: { colspan: "7" }
          })
        ]
      })
    );
  }
  table.append(body);
  return element("div", {
    className: "table-scroll native-table-scroll",
    attributes: {
      "data-testid": "table-scroll",
      tabindex: "0"
    },
    children: [
      table,
      element("div", {
        className: "sticky-total",
        attributes: { "data-testid": "sticky-total" },
        children: [
          element("span", {
            text: `${String(options.state.rows.length)}행 합계`
          }),
          element("strong", {
            text: "0원",
            attributes: {
              "data-testid": "preview-total",
              "data-won": "0"
            }
          })
        ]
      })
    ]
  });
}

function createHeader(): HTMLTableSectionElement {
  return element("thead", {
    children: [
      element("tr", {
        children: ["분야", "품명", "규격", "단위", "수량", "가격 방식", "금액"].map(
          (label) => element("th", { text: label, attributes: { scope: "col" } })
        )
      })
    ]
  });
}

function createRow(
  options: NativeViewOptions,
  row: NativeDraftRow,
  index: number
): HTMLTableRowElement {
  const selected = row.id === options.state.selectedId;
  const tableRow = element("tr", {
    className: selected ? "estimate-row is-selected" : "estimate-row",
    attributes: {
      "data-testid": "estimate-row",
      "data-row-id": row.id,
      "aria-selected": String(selected)
    }
  });
  tableRow.append(
    element("td", { children: [fieldSelect(options, row)] }),
    inputCell(options, row, index, "itemName", row.itemName, "품명"),
    inputCell(
      options,
      row,
      index,
      "specification",
      row.specification,
      "규격"
    ),
    inputCell(options, row, index, "unit", row.unit, "단위"),
    inputCell(options, row, index, "quantity", row.quantity, "수량"),
    element("td", {
      className: "method-cell",
      text: methodLabel(row.method)
    }),
    element("td", {
      className: "number-cell",
      text: "검증 전",
      attributes: { "data-line-amount": row.id }
    })
  );
  tableRow.addEventListener("click", () => {
    if (options.state.selectedId !== row.id) {
      options.events.selectRow(row);
    }
  });
  return tableRow;
}

function fieldSelect(
  options: NativeViewOptions,
  row: NativeDraftRow
): HTMLSelectElement {
  const select = element("select", {
    attributes: {
      "data-field": "field",
      "aria-label": `${row.id} 분야`
    },
    children: (["CCTV", "LAN", "FIBER"] as const).map((field) =>
      element("option", { text: field, attributes: { value: field } })
    )
  });
  select.value = row.field;
  select.addEventListener("change", () => {
    row.field = parseField(select.value);
    options.events.updateDerived();
  });
  return select;
}

function inputCell(
  options: NativeViewOptions,
  row: NativeDraftRow,
  index: number,
  field: "itemName" | "specification" | "unit" | "quantity",
  value: string,
  label: string
): HTMLTableCellElement {
  const input = element("input", {
    className: "cell-input",
    attributes: {
      "data-field": field,
      "data-grid-row": String(index),
      "data-grid-column": String(["itemName", "specification", "unit", "quantity"].indexOf(field)),
      "aria-label": `${String(index + 1)}행 ${label}`,
      autocomplete: "off",
      spellcheck: "false"
    }
  });
  input.value = value;
  bindComposingText(
    input,
    (next) => {
      row[field] = next;
    },
    options.events.updateDerived
  );
  return element("td", { children: [input] });
}

function methodLabel(method: NativeDraftRow["method"]): string {
  switch (method) {
    case "direct":
      return "직접";
    case "three_company_min":
      return "3사 최저";
    case "market_price":
      return "공식 시장";
    case "standard_quantity":
      return "표준품셈";
    default:
      return assertNever(method);
  }
}

function parseField(value: string): NativeField {
  return value === "LAN" ? "LAN" : value === "FIBER" ? "FIBER" : "CCTV";
}

function assertNever(value: never): never {
  throw new TypeError(`Unexpected method: ${String(value)}`);
}
