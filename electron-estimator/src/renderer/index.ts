import baseStyles from "./styles.css?inline";
import inspectorStyles from "./inspector.css?inline";
import legacyStyles from "./legacy-workflow.css?inline";
import nativeStyles from "./native-workflow.css?inline";
import shellStyles from "./workbench-shell.css?inline";
import tableStyles from "./workbench-table.css?inline";
import { renderNativeWorkflow } from "../workflows/native/controller.js";
import { applyDesignTokens } from "./tokens.js";
import { renderLegacyWorkflow } from "./legacy-workflow.js";

const sheet = new CSSStyleSheet();
sheet.replaceSync(
  [
    baseStyles,
    shellStyles,
    tableStyles,
    inspectorStyles,
    nativeStyles,
    legacyStyles
  ].join("\n")
);
document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];

applyDesignTokens(document.documentElement);

const app = document.querySelector<HTMLElement>("#app");
if (app !== null) {
  let cleanup = (): void => undefined;
  const showNative = (): void => {
    cleanup();
    cleanup = renderNativeWorkflow(app);
  };
  const showLegacy = (): void => {
    cleanup();
    cleanup = renderLegacyWorkflow(app);
  };
  globalThis.addEventListener("estimator:open-native", showNative);
  globalThis.addEventListener("estimator:open-legacy", showLegacy);
  showNative();
}
