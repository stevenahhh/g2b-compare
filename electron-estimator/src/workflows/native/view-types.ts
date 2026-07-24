import type {
  MarketPriceRow,
  ProductivityRow
} from "../../official/schemas.js";
import type { NativeDraftRow, NativeWorkflowState } from "./state.js";

export type NativeViewEvents = {
  readonly updateDerived: () => void;
  readonly rerender: (focusCatalog?: boolean) => void;
  readonly addRow: () => void;
  readonly selectRow: (row: NativeDraftRow) => void;
  readonly addMarket: (
    row: MarketPriceRow,
    mode: "new" | "selected"
  ) => void;
  readonly addProductivity: (
    row: ProductivityRow,
    mode: "new" | "selected"
  ) => void;
  readonly runSelector: (row: NativeDraftRow) => Promise<void>;
  readonly openExport: () => void;
  readonly openInspector: () => void;
  readonly closeInspector: () => void;
};

export type NativeViewOptions = {
  readonly state: NativeWorkflowState;
  readonly events: NativeViewEvents;
};
