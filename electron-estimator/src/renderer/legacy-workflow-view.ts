import { DESIGN_CONTRACT } from "./design-contract.js";
import { element } from "./dom.js";
import type { PatchCellInput } from "../legacy/patch/types.js";
import type {
  LegacyImportSession,
  LegacyWorkflowErrorCode
} from "../workflows/legacy/contracts.js";
import {
  createLegacyInspector,
  createLegacyValidationFooter,
  createLoadedWorkspace
} from "./legacy-workflow-panels.js";

export type LegacyWorkflowViewState = {
  readonly session: LegacyImportSession | null;
  readonly itemCount: number;
  readonly cells: readonly PatchCellInput[];
  readonly errors: readonly LegacyWorkflowErrorCode[];
  readonly status: string;
  readonly importing: boolean;
  readonly exporting: boolean;
};

export type LegacyWorkflowViewEvents = {
  readonly importWorkbook: () => void;
  readonly exportWorkbook: () => void;
  readonly openNative: () => void;
  readonly updateItemCount: (input: HTMLInputElement) => void;
  readonly updateCell: (input: HTMLInputElement) => void;
  readonly navigateCell: (
    input: HTMLInputElement,
    event: KeyboardEvent
  ) => void;
  readonly compositionStart: (input: HTMLInputElement) => void;
  readonly compositionEnd: (input: HTMLInputElement) => void;
};

export function createLegacyWorkflowView(input: {
  readonly state: LegacyWorkflowViewState;
  readonly events: LegacyWorkflowViewEvents;
}): HTMLElement {
  const { state, events } = input;
  const importButton = actionButton(
    "원본 XLSX 가져오기",
    "import-legacy",
    events.importWorkbook
  );
  importButton.disabled = state.importing || state.exporting;
  const exportButton = actionButton(
    "검토초안 + 검증 JSON 저장",
    "export-legacy",
    events.exportWorkbook,
    "button button-primary"
  );
  exportButton.disabled =
    state.session === null || state.errors.length > 0 || state.exporting;
  return element("div", {
    className: "legacy-workflow",
    attributes: {
      "data-testid": "legacy-workflow",
      "data-profile": state.session?.profileId ?? "",
      "data-source-sha256": state.session?.sourceSha256 ?? ""
    },
    children: [
      element("main", {
        className: "workbench-shell legacy-shell",
        children: [
          navigation(events.openNative),
          element("section", {
            className: "center-pane legacy-center",
            attributes: { "data-testid": "center-pane" },
            children: [
              header(state, importButton, exportButton),
              notices(),
              state.session === null
                ? emptyState()
                : createLoadedWorkspace(state, events),
              createLegacyValidationFooter(state)
            ]
          }),
          element("aside", {
            className: "provenance-inspector legacy-inspector",
            attributes: {
              "aria-label": "원본 및 검증 요약",
              "data-testid": "legacy-inspector"
            },
            children: createLegacyInspector(state.session)
          })
        ]
      })
    ]
  });
}

function header(
  state: LegacyWorkflowViewState,
  importButton: HTMLButtonElement,
  exportButton: HTMLButtonElement
): HTMLElement {
  return element("header", {
    className: "workspace-header legacy-header",
    children: [
      element("div", {
        children: [
          element("h1", { text: "고정 레거시 내역서 검토" }),
          element("p", {
            text:
              state.session?.sourceName ??
              "검증된 A/B/C 원본만 가져올 수 있음"
          })
        ]
      }),
      element("div", {
        className: "header-actions",
        children: [importButton, exportButton]
      })
    ]
  });
}

function navigation(openNative: () => void): HTMLElement {
  const native = element("button", {
    className: "rail-item",
    attributes: {
      type: "button",
      "data-testid": "open-native-workflow"
    },
    children: [
      element("span", { className: "rail-mark", text: "6" }),
      element("span", { className: "rail-label", text: "신규 6시트" })
    ]
  });
  native.addEventListener("click", openNative);
  return element("nav", {
    className: "left-rail",
    attributes: { "data-testid": "left-rail", "aria-label": "작업공간" },
    children: [
      element("div", {
        className: "rail-brand",
        children: [
          element("span", { className: "rail-mark", text: "LX" }),
          element("strong", { className: "rail-label", text: "레거시 XLSX" })
        ]
      }),
      native
    ]
  });
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

function emptyState(): HTMLElement {
  return element("section", {
    className: "legacy-empty",
    children: [
      element("h2", { text: "원본 파일을 먼저 선택해야 함" }),
      element("p", {
        text:
          "파일 경로는 renderer에 노출되지 않으며 main process에서 SHA-256과 프로필을 검증함."
      })
    ]
  });
}

function actionButton(
  text: string,
  testId: string,
  action: () => void,
  className = "button button-secondary"
): HTMLButtonElement {
  const button = element("button", {
    className,
    text,
    attributes: { type: "button", "data-testid": testId }
  });
  button.addEventListener("click", action);
  return button;
}
