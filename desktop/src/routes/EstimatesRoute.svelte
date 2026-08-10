<script lang="ts">
  import { onMount } from "svelte";

  import ConfirmModal from "../lib/components/ConfirmModal.svelte";
  import EstimateSummaryCard from "../lib/components/EstimateSummaryCard.svelte";
  import type { EstimateChangeEvent } from "../lib/estimateEvents";
  import type { EstimateClient } from "../lib/invoke";
  import type { CreateEstimateRequest, EstimateSummary } from "../lib/models";

  let {
    client,
    onNavigate,
    onReconciliation = () => undefined,
    createId = randomId,
    now = () => new Date(),
    externalChange = null,
    estimateChangeVersion = 0,
  }: {
    client: EstimateClient;
    onNavigate: (path: string) => void;
    onReconciliation?: () => void;
    createId?: () => string;
    now?: () => Date;
    externalChange?: EstimateChangeEvent | null;
    estimateChangeVersion?: number;
  } = $props();

  let summaries = $state<EstimateSummary[]>([]);
  let loading = $state(true);
  let creating = $state(false);
  let deleting = $state<string | null>(null);
  let error = $state("");
  let refreshVersion = 0;
  let handledChangeVersion = 0;
  let disposed = false;

  function randomId(): string {
    return [...crypto.getRandomValues(new Uint8Array(16))]
      .map((value) => value.toString(16).padStart(2, "0"))
      .join("");
  }

  function titleFor(sequence: number): string {
    const value = now();
    const day = `${value.getFullYear()}${String(value.getMonth() + 1).padStart(2, "0")}${String(value.getDate()).padStart(2, "0")}`;
    const time = `${String(value.getHours()).padStart(2, "0")}${String(value.getMinutes()).padStart(2, "0")}${String(value.getSeconds()).padStart(2, "0")}`;
    return `${sequence}-${day}-${time}`;
  }

  function message(caught: unknown): string {
    return caught instanceof Error ? caught.message : String(caught);
  }

  function isCurrentRefresh(version: number): boolean {
    return !disposed && version === refreshVersion;
  }

  async function refresh() {
    const version = ++refreshVersion;
    loading = true;
    error = "";
    try {
      const loaded = await client.listEstimates();
      if (!isCurrentRefresh(version)) return;
      summaries = loaded
        .filter((summary) => summary.line_count > 0)
        .sort((left, right) => right.updated_at.localeCompare(left.updated_at));
    } catch (caught) {
      if (isCurrentRefresh(version)) error = message(caught);
    } finally {
      if (isCurrentRefresh(version)) loading = false;
    }
  }

  async function createEstimate() {
    if (creating) return;
    creating = true;
    error = "";
    const request: CreateEstimateRequest = {
      id: createId(),
      title: titleFor(summaries.length + 1),
      template_sha256: "",
      lines: [],
      comparisons: [],
    };
    try {
      const created = await client.createEstimate(request);
      onReconciliation();
      await client.saveEstimateView({ active_estimate_id: created.id });
      onNavigate(`/estimates/${encodeURIComponent(created.id)}`);
    } catch (caught) {
      error = message(caught);
      onReconciliation();
      creating = false;
    }
  }

  async function openEstimate(id: string) {
    await client.saveEstimateView({ active_estimate_id: id });
    onNavigate(`/estimates/${encodeURIComponent(id)}`);
  }

  async function removeEstimate() {
    const id = deleting;
    deleting = null;
    if (!id) return;
    const operationVersion = ++refreshVersion;
    error = "";
    try {
      await client.deleteEstimate(id);
      if (disposed || operationVersion !== refreshVersion) return;
      summaries = summaries.filter((summary) => summary.id !== id);
      onReconciliation();
    } catch (caught) {
      if (disposed || operationVersion !== refreshVersion) return;
      error = message(caught);
      onReconciliation();
    }
  }

  $effect(() => {
    if (!externalChange || estimateChangeVersion <= handledChangeVersion) return;
    handledChangeVersion = estimateChangeVersion;
    void refresh();
  });

  onMount(() => {
    void refresh();
    return () => {
      disposed = true;
      refreshVersion += 1;
    };
  });
</script>

<header class="page-header page-header--split">
  <div class="page-header__copy"><h2>문서 작성</h2><p>저장된 비교 문서를 열거나 새 문서를 만듭니다.</p></div>
  <div class="page-actions"><button type="button" disabled={creating} onclick={() => void createEstimate()}>{creating ? "새 문서 여는 중" : "새 문서"}</button></div>
</header>
{#if error}<p class="state-message state-message--error" role="status">{error}</p>{/if}
{#if loading}
  <section class="empty-state estimate-state" aria-busy="true"><h3>저장된 내역 확인 중</h3><p>로컬 문서 저장소를 읽고 있습니다.</p></section>
{:else if summaries.length}
  <section class="estimate-list" aria-label="저장된 문서">
    {#each summaries as summary (summary.id)}
      <EstimateSummaryCard {summary} onOpen={(id) => void openEstimate(id)} onDelete={(id) => deleting = id} />
    {/each}
  </section>
{:else}
  <section class="empty-state estimate-state"><h3>저장된 내역 없음</h3><p>새 문서를 만들거나 물품 검색에서 품목을 추가하세요.</p></section>
{/if}
{#if deleting}
  <ConfirmModal title="문서 삭제" message="이 문서를 영구적으로 삭제할까요?" confirmLabel="삭제" onConfirm={() => void removeEstimate()} onCancel={() => deleting = null} />
{/if}
