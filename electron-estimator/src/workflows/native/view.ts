import { element } from "../../renderer/dom.js";
import { createCatalog } from "./view-catalog.js";
import {
  createHeader,
  createNotices,
  createProjectFields
} from "./view-fields.js";
import { createInspector } from "./view-inspector.js";
import { createEstimateTable } from "./view-table.js";
import type { NativeViewOptions } from "./view-types.js";

export function createNativeWorkflowView(
  options: NativeViewOptions
): HTMLElement {
  const shell = element("main", {
    className: "workbench-shell native-shell",
    attributes: { "data-testid": "workbench-shell" },
    children: [
      navigation(),
      element("section", {
        className: "center-pane native-center",
        attributes: { "data-testid": "center-pane" },
        children: [
          createHeader(options),
          createNotices(),
          element("div", {
            className: "native-workspace-scroll",
            children: [
              createProjectFields(options),
              createCatalog(options),
              createEstimateTable(options)
            ]
          }),
          validationFooter(options)
        ]
      }),
      createInspector(options)
    ]
  });
  return element("div", {
    className: "native-workflow",
    attributes: { "data-testid": "native-workflow" },
    children: [shell]
  });
}

function navigation(): HTMLElement {
  return element("nav", {
    className: "left-rail",
    attributes: {
      "data-testid": "left-rail",
      "aria-label": "작업공간"
    },
    children: [
      railItem("견", "견적 편집", true),
      railItem("출", "출처 검토", false),
      railItem("검", "검증 내역", false)
    ]
  });
}

function railItem(
  mark: string,
  label: string,
  current: boolean
): HTMLElement {
  return element(current ? "div" : "button", {
    className: current ? "rail-brand" : "rail-item",
    attributes: current
      ? {}
      : { type: "button", "aria-label": label },
    children: [
      element("span", { className: "rail-mark", text: mark }),
      element("span", { className: "rail-label", text: label })
    ]
  });
}

function validationFooter(options: NativeViewOptions): HTMLElement {
  return element("footer", {
    className: "native-validation-footer",
    children: [
      element("ul", {
        className: "validation-errors",
        attributes: {
          "data-testid": "validation-errors",
          "aria-live": "polite"
        }
      }),
      element("p", {
        text: options.state.status,
        attributes: {
          "data-testid": "export-result",
          "aria-live": "polite"
        }
      })
    ]
  });
}
