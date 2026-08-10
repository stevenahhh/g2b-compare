<script lang="ts">
  import { onDestroy } from "svelte";

  import type { DocumentActionClient } from "../invoke";
  import type { ComparisonSlot, EstimateDocument } from "../models";
  import { createTransientFeedbackDeadline } from "../transientFeedback";

  const slots: ComparisonSlot[] = ["A", "B", "C"];

  let {
    document,
    client,
    disabled = false,
  }: {
    document: EstimateDocument;
    client: DocumentActionClient;
    disabled?: boolean;
  } = $props();

  let action = $state<"copy" | "export" | null>(null);
  let status = $state("");
  let failed = $state(false);
  const feedbackDeadline = createTransientFeedbackDeadline(() => {
    status = "";
    failed = false;
  });
  const exportReady = $derived(
    document.lines.length > 0
      && document.lines.every((line) => slots.every(
        (slot) => line.comparisons.some((comparison) => comparison.slot === slot),
      )),
  );

  async function copyTable() {
    if (action) return;
    action = "copy";
    feedbackDeadline.cancel();
    status = "";
    failed = false;
    try {
      const result = await client.copyEstimateTable(document.id);
      status = `표 복사됨 · ${result.row_count.toLocaleString()}행`;
    } catch {
      failed = true;
      status = "표를 복사하지 못했습니다.";
    } finally {
      action = null;
      feedbackDeadline.reset();
    }
  }

  async function exportWorkbook() {
    if (action || !exportReady) return;
    action = "export";
    feedbackDeadline.cancel();
    status = "";
    failed = false;
    try {
      const result = await client.exportEstimateWorkbook(document.id);
      status = `XLSX 저장됨 · ${result.file_name}`;
    } catch {
      failed = true;
      status = "XLSX 파일을 저장하지 못했습니다.";
    } finally {
      action = null;
      feedbackDeadline.reset();
    }
  }

  onDestroy(feedbackDeadline.cancel);
</script>

<div class="document-actions">
  <button class="button button--secondary" type="button" disabled={disabled || Boolean(action) || document.lines.length === 0} onclick={() => void copyTable()}>{action === "copy" ? "복사 중" : "표 복사"}</button>
  {#if exportReady}<button class="button button--secondary" type="button" disabled={disabled || Boolean(action)} onclick={() => void exportWorkbook()}>{action === "export" ? "저장 중" : "XLSX 내보내기"}</button>{/if}
  {#if status}<p class:state-message--error={failed} class:state-message--success={!failed} class="document-actions__status state-message" role="status">{status}</p>{/if}
</div>
