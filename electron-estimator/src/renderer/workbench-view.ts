import { DESIGN_CONTRACT } from "./design-contract.js";
import { element } from "./dom.js";
import { createEstimateTable } from "./estimate-table.js";
import { createInspector } from "./provenance-inspector.js";
import type { WorkbenchRow } from "./workbench-model.js";
import type {
  NavigationSection,
  WorkbenchState
} from "./workbench-state.js";

type ViewOptions = {
  readonly state: WorkbenchState;
  readonly visibleRows: readonly WorkbenchRow[];
  readonly selected: WorkbenchRow;
  readonly narrow: boolean;
  readonly onOpenInspector: () => void;
  readonly onCloseInspector: () => void;
  readonly onSelectRow: (id: string) => void;
  readonly onDensityChange: (event: Event) => void;
  readonly onNavigate: (section: NavigationSection) => void;
};

function navigation(options: ViewOptions): HTMLElement {
  const nav = element("nav", {
    className: "left-rail",
    attributes: {
      "data-testid": "left-rail",
      "aria-label": "작업공간"
    },
    children: [
      element("div", {
        className: "rail-brand",
        children: [
          element("span", { className: "rail-mark", text: "견" }),
          element("strong", { className: "rail-label", text: "견적 검토" })
        ]
      })
    ]
  });
  const items = [
    ["표", "견적 편집", "estimate"],
    ["출", "출처 검토", "provenance"],
    ["검", "검증 내역", "validation"]
  ] as const;
  for (const [mark, label, section] of items) {
    const current = options.state.activeNav === section;
    const button = element("button", {
      className: current ? "rail-item is-current" : "rail-item",
      attributes: {
        type: "button",
        "aria-current": current ? "page" : "false"
      },
      children: [
        element("span", { className: "rail-mark", text: mark }),
        element("span", { className: "rail-label", text: label })
      ]
    });
    button.addEventListener("click", () => options.onNavigate(section));
    nav.append(button);
  }
  return nav;
}

function notices(): HTMLElement {
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

function header(state: WorkbenchState): HTMLElement {
  return element("header", {
    className: "workspace-header",
    children: [
      element("div", {
        children: [
          element("h1", { text: "통신공사 견적 편집" }),
          element("p", {
            text: "프로젝트: 2026 여름 CCTV · 템플릿: 신규견적 · 출처: 공식 2026 + 조달 관측"
          })
        ]
      }),
      element("span", {
        className: state.dirty ? "dirty-state is-dirty" : "dirty-state",
        text: state.dirty ? "저장되지 않음" : "로컬 상태 저장됨",
        attributes: { "data-testid": "dirty-state" }
      })
    ]
  });
}

function toolbar(options: ViewOptions): HTMLElement {
  const search = element("input", {
    attributes: {
      type: "search",
      placeholder: "표 안에서 찾기 (Ctrl+F)",
      "aria-label": "견적 표 검색",
      "data-testid": "table-search"
    }
  });
  search.value = options.state.query;
  const density = element("select", {
    attributes: {
      "aria-label": "행 밀도",
      "data-testid": "density-select"
    },
    children: [
      element("option", { text: "압축 26", attributes: { value: "compact" } }),
      element("option", { text: "기본 32", attributes: { value: "regular" } }),
      element("option", {
        text: "여유 40",
        attributes: { value: "comfortable" }
      })
    ]
  });
  density.value = options.state.density;
  density.addEventListener("change", options.onDensityChange);
  const inspectorButton = element("button", {
    className: "button button-secondary",
    text: "출처 보기",
    attributes: { type: "button", "data-testid": "open-inspector" }
  });
  inspectorButton.addEventListener("click", options.onOpenInspector);
  return element("div", {
    className: "workbench-toolbar",
    children: [search, density, inspectorButton]
  });
}

function status(): HTMLElement {
  return element("div", {
    className: "workbench-status",
    children: [
      element("span", {
        text: "Tab · Shift+Tab · 방향키 · Enter · F2 · Esc · Ctrl+F"
      }),
      element("span", {
        attributes: {
          "data-testid": "live-region",
          "aria-live": "polite",
          "aria-atomic": "true",
          tabindex: "-1"
        },
        text: "편집 준비됨."
      })
    ]
  });
}

export function createWorkbenchView(options: ViewOptions): readonly Node[] {
  const center = element("section", {
    className: "center-pane",
    attributes: { "data-testid": "center-pane" },
    children: [
      header(options.state),
      notices(),
      toolbar(options),
      createEstimateTable({
        rows: options.visibleRows,
        selectedId: options.state.selectedId,
        density: options.state.density,
        onSelect: options.onSelectRow
      }),
      status()
    ]
  });
  return [
    navigation(options),
    center,
    createInspector(
      options.selected,
      options.narrow,
      options.state.inspectorOpen,
      options.onCloseInspector
    )
  ];
}
