import { element } from "../../renderer/dom.js";
import {
  createNativeInspectorDto,
  type InspectorDefinition
} from "./inspector.js";
import type { NativeDraftRow } from "./state.js";
import { createSourceEditor } from "./view-source-editor.js";
import type { NativeViewOptions } from "./view-types.js";
import { validateNativeWorkflow } from "./validation.js";

export function createInspector(options: NativeViewOptions): HTMLElement {
  const narrow = globalThis.matchMedia("(max-width: 1024px)").matches;
  const row = options.state.rows.find(
    (candidate) => candidate.id === options.state.selectedId
  );
  if (row === undefined) {
    const children: HTMLElement[] = [
      element("div", {
        className: "empty-source",
        text: "행을 추가하거나 선택하면 출처 편집기가 표시됨."
      })
    ];
    if (narrow && options.state.inspectorOpen) {
      const close = inspectorClose(options);
      children.unshift(close);
    }
    return element("aside", {
      className: `provenance-inspector native-inspector${!narrow || options.state.inspectorOpen ? " is-open" : ""}`,
      attributes: {
        "data-testid": "provenance-inspector",
        "aria-label": "선택 행 출처 inspector",
        ...(narrow
          ? {
              role: "dialog",
              "aria-modal": "true",
              "aria-hidden": String(!options.state.inspectorOpen)
            }
          : { role: "complementary" })
      },
      children
    });
  }
  const validation = validateNativeWorkflow(options.state);
  const calculation = validation.ok
    ? validation.calculation.lines.find((line) => line.lineId === row.id)
    : undefined;
  const dto = createNativeInspectorDto(row, calculation);
  const heading = element("div", {
    className: "inspector-heading",
    children: [
      element("h2", {
        text: "출처 및 계산 근거",
        children: [element("span", { className: "selected-line", text: row.itemName })]
      })
    ]
  });
  if (dto.koreaNetSelected) {
    heading.append(
      element("span", {
        className: "status-badge status-badge-success",
        text: "KoreaNet 자동선택",
        attributes: { "data-testid": "koreanet-badge" }
      })
    );
  }
  if (narrow) {
    heading.append(inspectorClose(options));
  }
  return element("aside", {
    className: `provenance-inspector native-inspector${!narrow || options.state.inspectorOpen ? " is-open" : ""}`,
    attributes: {
      "data-testid": "provenance-inspector",
      "aria-label": "선택 행 출처 inspector",
      ...(narrow
        ? {
            role: "dialog",
            "aria-modal": "true",
            "aria-hidden": String(!options.state.inspectorOpen)
          }
        : { role: "complementary" })
    },
    children: [
      heading,
      element("div", {
        className: "inspector-body",
        children: [
          methodEditor(options, row),
          createSourceEditor(options, row),
          calculationSummary(dto),
          definitionList(dto.definitions),
          ...(dto.selectorDto.length === 0
            ? []
            : [
                element("pre", {
                  className: "selector-dto",
                  text: dto.selectorDto,
                  attributes: { "data-testid": "selector-dto" }
                })
              ])
        ]
      })
    ]
  });
}

function inspectorClose(options: NativeViewOptions): HTMLButtonElement {
  const close = element("button", {
    className: "inspector-close",
    text: "닫기",
    attributes: {
      type: "button",
      "data-testid": "close-inspector",
      "aria-label": "출처 inspector 닫기"
    }
  });
  close.addEventListener("click", options.events.closeInspector);
  return close;
}

function methodEditor(
  options: NativeViewOptions,
  row: NativeDraftRow
): HTMLElement {
  const select = element("select", {
    attributes: {
      "data-testid": "cost-method",
      "aria-label": "가격 방식"
    },
    children: ([
      ["direct", "직접 사용자·조달 출처"],
      ["three_company_min", "3사 최저가"],
      ["market_price", "공식 시장단가"],
      ["standard_quantity", "표준품셈 수량×노임"]
    ] as const).map(([value, text]) =>
      element("option", { text, attributes: { value: value ?? "" } })
    )
  });
  select.value = row.method;
  select.addEventListener("change", () => {
    const value = select.value;
    if (
      value === "direct" ||
      value === "three_company_min" ||
      value === "market_price" ||
      value === "standard_quantity"
    ) {
      row.method = value;
      options.events.rerender();
    }
  });
  const clear = element("button", {
    className: "button button-secondary",
    text: "공식 연결 초기화",
    attributes: { type: "button" }
  });
  clear.addEventListener("click", () => {
    row.market = null;
    row.productivity = null;
    if (row.method === "market_price" || row.method === "standard_quantity") {
      row.method = "direct";
    }
    options.events.rerender();
  });
  return element("section", {
    className: "source-editor method-editor",
    children: [
      element("h3", { text: "가격 방식" }),
      select,
      ...(row.market !== null && row.productivity !== null ? [clear] : [])
    ]
  });
}

function calculationSummary(
  dto: ReturnType<typeof createNativeInspectorDto>
): HTMLElement {
  return element("section", {
    className: "calculation-summary",
    children: [
      element("h3", { text: "계산 기여" }),
      element("p", {
        text: dto.formulaContribution,
        attributes: { "data-testid": "formula-contribution" }
      }),
      element("p", {
        text: dto.selectedSupplier,
        attributes: { "data-testid": "selected-supplier" }
      }),
      element("p", {
        className: "selection-reason",
        text: dto.selectionReason,
        attributes: { "data-testid": "selection-reason" }
      })
    ]
  });
}

function definitionList(
  definitions: readonly InspectorDefinition[]
): HTMLElement {
  return element("dl", {
    className: "inspector-definitions",
    children: definitions.map((item) =>
      element("div", {
        className: "inspector-definition",
        attributes: {
          [item.kind === "provenance"
            ? "data-provenance-field"
            : "data-evidence-field"]: item.label
        },
        children: [
          element("dt", { text: item.label }),
          element("dd", { text: item.value })
        ]
      })
    )
  });
}
