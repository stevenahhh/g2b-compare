import { element } from "./dom.js";
import type { Density, WorkbenchRow } from "./workbench-model.js";

const number = new Intl.NumberFormat("ko-KR");

export const EDITABLE_FIELDS = [
  "itemName",
  "specification",
  "unit",
  "quantity",
  "unitPriceWon"
] as const;

export type EditableField = (typeof EDITABLE_FIELDS)[number];

type TableOptions = {
  readonly rows: readonly WorkbenchRow[];
  readonly selectedId: string;
  readonly density: Density;
  readonly onSelect: (id: string) => void;
};

function inputCell(
  value: string,
  rowIndex: number,
  columnIndex: number,
  field: EditableField,
  label: string
): HTMLTableCellElement {
  const input = element("input", {
    className: "cell-input",
    attributes: {
      value,
      "aria-label": label,
      "data-grid-row": String(rowIndex),
      "data-grid-column": String(columnIndex),
      "data-field": field,
      autocomplete: "off",
      spellcheck: "false"
    }
  });
  input.value = value;
  return element("td", { children: [input] });
}

function rowSubtotal(row: WorkbenchRow): number {
  const quantity = Number.parseFloat(row.quantity);
  return Number.isFinite(quantity) ? quantity * row.unitPriceWon : 0;
}

function createRow(
  row: WorkbenchRow,
  rowIndex: number,
  selectedId: string,
  select: (id: string) => void
): HTMLTableRowElement {
  const tableRow = element("tr", {
    className: row.id === selectedId ? "estimate-row is-selected" : "estimate-row",
    attributes: {
      "data-testid": "estimate-row",
      "data-row-id": row.id,
      "aria-selected": String(row.id === selectedId)
    },
    children: [
      inputCell(
        row.itemName,
        rowIndex,
        0,
        "itemName",
        `${String(rowIndex + 1)}행 품명`
      ),
      inputCell(
        row.specification,
        rowIndex,
        1,
        "specification",
        `${String(rowIndex + 1)}행 규격`
      ),
      inputCell(
        row.unit,
        rowIndex,
        2,
        "unit",
        `${String(rowIndex + 1)}행 단위`
      ),
      inputCell(
        row.quantity,
        rowIndex,
        3,
        "quantity",
        `${String(rowIndex + 1)}행 수량`
      ),
      inputCell(
        number.format(row.unitPriceWon),
        rowIndex,
        4,
        "unitPriceWon",
        `${String(rowIndex + 1)}행 적용단가`
      ),
      element("td", {
        className: "number-cell",
        text: `${number.format(rowSubtotal(row))}원`
      })
    ]
  });
  tableRow.addEventListener("click", (event) => {
    if (!(event.target instanceof HTMLInputElement)) {
      select(row.id);
    }
  });
  return tableRow;
}

function createHeader(): HTMLTableSectionElement {
  const row = element("tr");
  const labels = [
    "품명",
    "규격",
    "단위",
    "수량",
    "적용단가",
    "금액"
  ] as const;
  for (const label of labels) {
    row.append(
      element("th", {
        text: label,
        attributes: { scope: "col" }
      })
    );
  }
  return element("thead", { children: [row] });
}

export function createEstimateTable(options: TableOptions): HTMLElement {
  const table = element("table", {
    className: "estimate-table",
    attributes: {
      "aria-label": "견적 편집 표",
      "data-density": options.density
    },
    children: [createHeader()]
  });
  const body = element("tbody");
  options.rows.forEach((row, rowIndex) => {
    body.append(
      createRow(row, rowIndex, options.selectedId, options.onSelect)
    );
  });
  if (options.rows.length === 0) {
    body.append(
      element("tr", {
        children: [
          element("td", {
            className: "empty-table",
            text: "검색 조건과 일치하는 행 없음.",
            attributes: { colspan: "6" }
          })
        ]
      })
    );
  }
  table.append(body);
  const total = options.rows.reduce((sum, row) => sum + rowSubtotal(row), 0);
  return element("div", {
    className: "table-scroll",
    attributes: {
      "data-testid": "table-scroll",
      "aria-busy": "false",
      tabindex: "0"
    },
    children: [
      table,
      element("div", {
        className: "sticky-total",
        attributes: {
          "data-testid": "sticky-total",
          role: "status"
        },
        children: [
          element("span", { text: `표시 ${String(options.rows.length)}행 합계` }),
          element("strong", { text: `${number.format(total)}원` })
        ]
      })
    ]
  });
}
