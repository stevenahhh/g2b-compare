import { relaunch } from "@tauri-apps/plugin-process";
import {
  check,
  type DownloadEvent,
} from "@tauri-apps/plugin-updater";

export interface AppUpdate {
  readonly version: string;
  readonly body: string | null;
  downloadAndInstall(onEvent: (event: DownloadEvent) => void): Promise<void>;
}

export interface UpdateClient {
  check(): Promise<AppUpdate | null>;
  relaunch(): Promise<void>;
}

export const desktopUpdateClient: UpdateClient = {
  check: async () => {
    const update = await check({ timeout: 10_000 });
    if (update === null) return null;
    return {
      version: update.version,
      body: update.body ?? null,
      downloadAndInstall: (onEvent) => update.downloadAndInstall(onEvent),
    };
  },
  relaunch,
};

export type { DownloadEvent };
