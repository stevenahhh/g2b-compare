import type { EditableField } from "./estimate-table.js";
import {
  createWorkbenchRows,
  type Density,
  type WorkbenchRow
} from "./workbench-model.js";

export type NavigationSection = "estimate" | "provenance" | "validation";

export type WorkbenchState = {
  rows: WorkbenchRow[];
  selectedId: string;
  density: Density;
  query: string;
  inspectorOpen: boolean;
  dirty: boolean;
  validationCount: number;
  saveCount: number;
  navigationCount: number;
  composing: HTMLInputElement | null;
  pendingNavigation: boolean;
  editBaseline: string;
  activeNav: NavigationSection;
};

export function createWorkbenchState(): WorkbenchState {
  const rows = createWorkbenchRows();
  return {
    rows,
    selectedId: rows[0]?.id ?? "",
    density: "regular",
    query: "",
    inspectorOpen: false,
    dirty: false,
    validationCount: 0,
    saveCount: 0,
    navigationCount: 0,
    composing: null,
    pendingNavigation: false,
    editBaseline: "",
    activeNav: "estimate"
  };
}

export function parseField(value: string | null): EditableField | null {
  switch (value) {
    case "itemName":
    case "specification":
    case "unit":
    case "quantity":
    case "unitPriceWon":
      return value;
    default:
      return null;
  }
}

export function updateRow(
  row: WorkbenchRow,
  field: EditableField,
  value: string
): void {
  switch (field) {
    case "itemName":
      row.itemName = value;
      return;
    case "specification":
      row.specification = value;
      return;
    case "unit":
      row.unit = value;
      return;
    case "quantity":
      row.quantity = value;
      return;
    case "unitPriceWon": {
      const parsed = Number(value.replaceAll(",", ""));
      if (Number.isSafeInteger(parsed) && parsed > 0) {
        row.unitPriceWon = parsed;
      }
      return;
    }
    default:
      return;
  }
}
