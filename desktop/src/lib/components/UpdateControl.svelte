<script lang="ts">
  import { onMount } from "svelte";

  import type {
    AppUpdate,
    DownloadEvent,
    UpdateClient,
  } from "../update";
  import { desktopUpdateClient } from "../update";
  import ConfirmModal from "./ConfirmModal.svelte";

  type UpdatePhase =
    | "checking"
    | "current"
    | "available"
    | "downloading"
    | "installing"
    | "installed"
    | "error";

  let {
    client = desktopUpdateClient,
  }: {
    client?: UpdateClient;
  } = $props();

  let phase = $state<UpdatePhase>("checking");
  let update = $state<AppUpdate | null>(null);
  let confirmationOpen = $state(false);
  let downloadedBytes = $state(0);
  let totalBytes = $state<number | null>(null);
  let errorMessage = $state("");

  const progress = $derived(
    totalBytes && totalBytes > 0
      ? Math.min(100, Math.round((downloadedBytes / totalBytes) * 100))
      : null,
  );

  async function checkForUpdate(): Promise<void> {
    phase = "checking";
    errorMessage = "";
    try {
      update = await client.check();
      phase = update === null ? "current" : "available";
    } catch (error) {
      if (!(error instanceof Error)) throw error;
      errorMessage = "업데이트 서버에 연결하지 못했습니다.";
      phase = "error";
    }
  }

  function receiveDownloadEvent(event: DownloadEvent): void {
    switch (event.event) {
      case "Started":
        totalBytes = event.data.contentLength ?? null;
        downloadedBytes = 0;
        phase = "downloading";
        return;
      case "Progress":
        downloadedBytes += event.data.chunkLength;
        return;
      case "Finished":
        phase = "installing";
    }
  }

  async function installUpdate(): Promise<void> {
    const selected = update;
    if (selected === null) return;
    confirmationOpen = false;
    phase = "downloading";
    try {
      await selected.downloadAndInstall(receiveDownloadEvent);
      phase = "installed";
      await client.relaunch();
    } catch (error) {
      if (!(error instanceof Error)) throw error;
      errorMessage = "업데이트 설치에 실패했습니다. 다시 시도해 주세요.";
      phase = "error";
    }
  }

  onMount(() => {
    void checkForUpdate();
  });
</script>

<div class="app-update" aria-live="polite">
  {#if phase === "available" && update}
    <button class="app-update__action" type="button" onclick={() => confirmationOpen = true}>
      {update.version} 업데이트
    </button>
  {:else if phase === "downloading"}
    <span class="app-update__status">
      <span class="loading-spinner" aria-hidden="true"></span>
      {progress === null ? "업데이트 다운로드 중" : `업데이트 ${progress}%`}
    </span>
  {:else if phase === "installing"}
    <span class="app-update__status">업데이트 설치 중</span>
  {:else if phase === "installed"}
    <span class="app-update__status app-update__status--success">업데이트 설치 완료</span>
  {:else if phase === "error"}
    <span class="app-update__error">{errorMessage}</span>
    <button class="app-update__retry" type="button" onclick={() => void checkForUpdate()}>
      업데이트 다시 확인
    </button>
  {/if}
</div>

{#if confirmationOpen && update}
  <ConfirmModal
    title={`${update.version} 업데이트`}
    message={`새 버전을 설치합니다. 사용자 데이터는 유지되며 앱이 다시 시작됩니다.${update.body ? `\n\n${update.body}` : ""}`}
    confirmLabel="설치 후 다시 시작"
    destructive={false}
    onConfirm={() => void installUpdate()}
    onCancel={() => confirmationOpen = false}
  />
{/if}
