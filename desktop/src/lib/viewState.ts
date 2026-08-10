import type { DesktopStateClient } from "./invoke";
import type { DesktopViewState } from "./models";

export interface DurableViewStateAdapter {
  load(): Promise<DesktopViewState | null>;
  save(state: DesktopViewState): Promise<void>;
}

export function createDurableViewStateAdapter(
  client: Pick<DesktopStateClient, "loadDesktopView" | "saveDesktopView">,
): DurableViewStateAdapter {
  return {
    load: () => client.loadDesktopView(),
    save: (state) => client.saveDesktopView(state),
  };
}

export function createLatestViewStateWriter(adapter: DurableViewStateAdapter) {
  let pending: DesktopViewState | null = null;
  let running: Promise<void> | null = null;

  const pump = () => {
    running = (async () => {
      while (pending) {
        const state = pending;
        pending = null;
        try {
          await adapter.save(state);
        } catch {
          // A failed persistence attempt must not discard a newer local view.
        }
      }
    })().finally(() => {
      running = null;
      if (pending) pump();
    });
  };

  return (state: DesktopViewState): Promise<void> | null => {
    pending = state;
    if (!running) pump();
    return running;
  };
}
