import { DESIGN_CONTRACT } from "../../renderer/design-contract.js";
import { element } from "../../renderer/dom.js";
import type { RateContextDraft } from "./state.js";
import type { NativeViewOptions } from "./view-types.js";
type TextBinding = {
  readonly value: string;
  readonly set: (value: string) => void;
};
export function createHeader(options: NativeViewOptions): HTMLElement {
  const { state } = options;
  const legacy = element("button", {
    className: "button button-secondary",
    text: "레거시 XLSX",
    attributes: {
      type: "button",
      "data-testid": "open-legacy-workflow"
    }
  });
  legacy.addEventListener("click", () => {
    globalThis.dispatchEvent(new Event("estimator:open-legacy"));
  });
  const inspect = element("button", {
    className: "button button-secondary",
    text: "출처 보기",
    attributes: { type: "button", "data-testid": "open-inspector" }
  });
  inspect.addEventListener("click", options.events.openInspector);
  const exportButton = element("button", {
    className: "button button-primary",
    text: "6시트 XLSX 저장",
    attributes: {
      type: "button",
      "data-testid": "export-workbook",
      disabled: ""
    }
  });
  exportButton.addEventListener("click", options.events.openExport);
  return element("header", {
    className: "workspace-header native-header",
    children: [
      element("div", {
        children: [
          element("h1", { text: "네이티브 통신공사 견적 편집" }),
          element("p", {
            text: state.catalog === null
              ? "공식 2026 고정본 확인 중"
              : `${state.catalog.revision.datasetVersion} · ${String(state.rows.length)}/200행`
          })
        ]
      }),
      element("div", {
        className: "header-actions",
        children: [legacy, inspect, exportButton]
      })
    ]
  });
}
export function createNotices(): HTMLElement {
  return element("div", {
    className: "workbench-notices",
    children: [
      element("p", {
        className: "workbench-notice legal-notice",
        text: DESIGN_CONTRACT.disclaimers.always,
        attributes: { "data-testid": "legal-notice" }
      }),
      element("p", {
        className: "workbench-notice unsigned-notice",
        text: DESIGN_CONTRACT.disclaimers.unsigned,
        attributes: { "data-testid": "unsigned-notice" }
      })
    ]
  });
}
export function createProjectFields(options: NativeViewOptions): HTMLElement {
  const { state, events } = options;
  const grid = element("section", {
    className: "native-project-grid",
    attributes: { "aria-label": "프로젝트 정보" }
  });
  grid.append(
    textField("프로젝트 ID", "project-id", {
      value: state.projectId,
      set: (value) => {
        state.projectId = value;
      }
    }, events.updateDerived),
    textField("프로젝트명", "project-name", {
      value: state.projectName,
      set: (value) => {
        state.projectName = value;
      }
    }, events.updateDerived),
    textField("작성일", "prepared-on", {
      value: state.preparedOn,
      set: (value) => {
        state.preparedOn = value;
      }
    }, events.updateDerived, "date")
  );
  grid.append(createRateContext(state.rateContext, events.updateDerived));
  return grid;
}
function createRateContext(
  context: RateContextDraft,
  update: () => void
): HTMLElement {
  const details = element("details", {
    className: "rate-context",
    attributes: { open: "" },
    children: [element("summary", { text: "공식단가 요율 문맥" })]
  });
  const grid = element("div", { className: "rate-context-grid" });
  grid.append(
    textField("발행자", "context-issuer", binding(context, "issuer"), update),
    selectField("구분", "context-regime", context.regime, [
      ["", "선택"],
      ["national", "국가"],
      ["local", "지방"]
    ], (value) => {
      context.regime =
        value === "national" || value === "local" ? value : "";
      update();
    }),
    textField(
      "공고·계약일",
      "context-date",
      binding(context, "noticeOrContractDate"),
      update,
      "date"
    ),
    textField(
      "프로젝트 유형",
      "context-project-type",
      binding(context, "projectType"),
      update
    ),
    selectField("도급 구분", "context-contract-level", context.contractLevel, [
      ["", "선택"],
      ["general", "원도급"],
      ["subcontract", "하도급"]
    ], (value) => {
      context.contractLevel =
        value === "general" || value === "subcontract" ? value : "";
      update();
    }),
    textField(
      "금액 기준",
      "context-amount-basis",
      binding(context, "amountBasis"),
      update
    ),
    selectField("관급재료", "context-supplied-materials", context.suppliedMaterials, [
      ["", "선택"],
      ["included", "포함"],
      ["excluded", "제외"],
      ["mixed", "혼합"]
    ], (value) => {
      context.suppliedMaterials =
        value === "included" || value === "excluded" || value === "mixed"
          ? value
          : "";
      update();
    }),
    textField(
      "가격 기준",
      "context-pricing-method",
      binding(context, "pricingMethod"),
      update
    ),
    selectField("부가세", "context-vat-status", context.vatStatus, [
      ["", "선택"],
      ["included", "포함"],
      ["excluded", "제외"],
      ["unknown", "확인 필요"]
    ], (value) => {
      context.vatStatus =
        value === "included" || value === "excluded" || value === "unknown"
          ? value
          : "";
      update();
    })
  );
  details.append(grid);
  return details;
}
export function textField(
  label: string,
  testId: string,
  bindingValue: TextBinding,
  update: () => void,
  type = "text"
): HTMLLabelElement {
  const input = element("input", {
    attributes: { type, "data-testid": testId, autocomplete: "off" }
  });
  input.value = bindingValue.value;
  bindComposingText(input, bindingValue.set, update);
  return element("label", {
    className: "field-label",
    children: [element("span", { text: label }), input]
  });
}
export function bindComposingText(
  input: HTMLInputElement | HTMLTextAreaElement,
  set: (value: string) => void,
  update: () => void
): void {
  let composing = false;
  input.addEventListener("compositionstart", () => {
    composing = true;
  });
  input.addEventListener("input", () => {
    set(input.value);
    if (!composing) {
      update();
    }
  });
  input.addEventListener("compositionend", () => {
    composing = false;
    set(input.value);
    update();
  });
}
function selectField(
  label: string,
  testId: string,
  value: string,
  options: readonly (readonly [string, string])[],
  update: (value: string) => void
): HTMLLabelElement {
  const select = element("select", {
    attributes: { "data-testid": testId },
    children: options.map(([optionValue, text]) =>
      element("option", { text, attributes: { value: optionValue } })
    )
  });
  select.value = value;
  select.addEventListener("change", () => update(select.value));
  return element("label", {
    className: "field-label",
    children: [element("span", { text: label }), select]
  });
}
type TextRateContextKey =
  | "issuer"
  | "noticeOrContractDate"
  | "projectType"
  | "amountBasis"
  | "pricingMethod";
function binding(
  context: RateContextDraft,
  key: TextRateContextKey
): TextBinding {
  return {
    value: context[key],
    set: (value) => {
      context[key] = value;
    }
  };
}
