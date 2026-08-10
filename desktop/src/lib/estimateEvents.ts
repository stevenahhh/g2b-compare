import type { UnlistenFn } from "@tauri-apps/api/event";
import { getCurrentWebviewWindow } from "@tauri-apps/api/webviewWindow";

export const ESTIMATE_CHANGE_EVENT = "estimate-change";

export type EstimateChangeKind = "saved" | "deleted";

export interface EstimateChangeEvent {
  id: string;
  kind: EstimateChangeKind;
  revision: number | null;
}

export type EstimateChangeListener = (change: EstimateChangeEvent) => void;
export type EstimateChangeSubscriber = (listener: EstimateChangeListener) => Promise<UnlistenFn>;

export const listenForEstimateChanges: EstimateChangeSubscriber = async (listener) =>
  getCurrentWebviewWindow().listen<EstimateChangeEvent>(
    ESTIMATE_CHANGE_EVENT,
    (event) => listener(event.payload),
  );
