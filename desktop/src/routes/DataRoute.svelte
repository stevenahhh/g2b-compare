<script lang="ts">
  import { onDestroy, onMount } from "svelte";

  import { DATA_COUNTS, safeDiagnosticMessage, syncStageLabel } from "../lib/data";
  import type { DesktopClient } from "../lib/invoke";
  import type { DataDiagnosticResult, DataStatus, DataSyncStatus } from "../lib/models";
  import { createTransientFeedbackDeadline } from "../lib/transientFeedback";

  const legacyTools = [
    ["우선 수집", "http://127.0.0.1:8765/priority"],
    ["동기화 상세", "http://127.0.0.1:8765/sync"],
    ["실시간 검색", "http://127.0.0.1:8765/live"],
  ] as const;

  let {
    client,
    onReconciliation = () => undefined,
  }: {
    client: DesktopClient;
    onReconciliation?: () => void;
  } = $props();

  let status = $state<DataStatus | null>(null);
  let loading = $state(true);
  let error = $state("");
  let sync = $state<DataSyncStatus | null>(null);
  let syncing = $state(false);
  let diagnostics = $state<DataDiagnosticResult | null>(null);
  let diagnosing = $state(false);
  let actionError = $state("");
  const actionFeedbackDeadline = createTransientFeedbackDeadline(() => {
    if (sync?.state !== "running") sync = null;
    diagnostics = null;
    actionError = "";
  });

  function beginActionFeedback() {
    actionFeedbackDeadline.cancel();
    if (sync?.state !== "running") sync = null;
    diagnostics = null;
    actionError = "";
  }

  async function load() {
    loading = true;
    error = "";
    try {
      const next = await client.getDataStatus();
      status = next;
      if (next.error) error = safeDiagnosticMessage(next.error);
    } catch (caught) {
      error = safeDiagnosticMessage(caught);
      onReconciliation();
    } finally {
      loading = false;
    }
  }

  async function runSync() {
    if (syncing) return;
    syncing = true;
    beginActionFeedback();
    sync = { state: "running", stage: "sync", error: null };
    try {
      sync = await client.runDataSync();
      if (sync.error || sync.state === "failed") {
        actionError = safeDiagnosticMessage(sync.error);
      } else {
        await load();
      }
    } catch (caught) {
      sync = { state: "failed", stage: sync?.stage ?? "sync", error: "data-unavailable" };
      actionError = safeDiagnosticMessage(caught);
      onReconciliation();
    } finally {
      syncing = false;
      actionFeedbackDeadline.reset();
    }
  }

  async function runDiagnostics() {
    if (diagnosing) return;
    diagnosing = true;
    beginActionFeedback();
    try {
      diagnostics = await client.runDataDiagnostics();
      if (diagnostics.code) actionError = safeDiagnosticMessage(diagnostics.code);
    } catch (caught) {
      actionError = safeDiagnosticMessage(caught);
      onReconciliation();
    } finally {
      diagnosing = false;
      actionFeedbackDeadline.reset();
    }
  }

  async function openLegacy(url: string) {
    beginActionFeedback();
    try {
      await client.openProduct(url);
    } catch {
      actionError = "기존 서버 도구를 열지 못했습니다. 로컬 서버가 실행 중인지 확인하세요.";
      actionFeedbackDeadline.reset();
    }
  }

  onMount(() => void load());
  onDestroy(actionFeedbackDeadline.cancel);
</script>

<header class="page-header page-header--split">
  <div class="page-header__copy">
    <h2>데이터 상태</h2>
    <p>로컬 적재 상태를 확인하고 명시적으로 동기화와 진단을 실행합니다.</p>
  </div>
  <div class="page-actions">
    <button class="button button--secondary" type="button" disabled={loading} onclick={() => void load()}>{loading ? "확인 중" : "새로고침"}</button>
  </div>
</header>

<section class:status-panel--warning={status && !status.ready} class:status-panel--error={Boolean(error)} class="panel status-panel" aria-busy={loading}>
  <div class="status-summary" role={error ? "alert" : "status"} aria-live="polite">
    {#if loading}<span class="loading-spinner" aria-hidden="true"></span>{:else}<span class:status-indicator--error={Boolean(error)} class:status-indicator--warning={status && !status.ready} class="status-indicator" aria-hidden="true"></span>{/if}
    <div>
      <strong>{loading ? "데이터 확인 중" : error ? "상태 확인 실패" : status?.ready ? "사용 준비됨" : "준비 확인 필요"}</strong>
      {#if loading}<p class="state-message">{status ? "기존 수치를 유지한 채 최신 상태를 확인합니다." : "로컬 데이터베이스를 읽고 있습니다."}</p>
      {:else if error}<p class="state-message state-message--error">{error}{status ? " · 마지막 확인 수치는 아래에 유지합니다." : ""}</p>
      {:else}<p class="state-message">준비 상태: {status?.readiness ?? "unknown"}</p>{/if}
    </div>
  </div>
</section>

{#if status || loading}
  <section class="status-counts" aria-label={error ? "마지막으로 확인된 데이터 개수" : "데이터 개수"}>
    {#each DATA_COUNTS as [label, key]}
      <article class="panel data-count">
        <span>{label}</span>
        {#if status}<strong>{Number(status[key]).toLocaleString()}</strong>{:else}<strong class="loading-placeholder loading-placeholder--number" aria-hidden="true"></strong>{/if}
      </article>
    {/each}
  </section>
{/if}

<section class="panel data-operations" aria-labelledby="data-operations-title">
  <div class="data-operations__header">
    <div><span class="section-eyebrow">수동 작업</span><h3 id="data-operations-title">동기화 및 진단</h3><p>네트워크 작업은 버튼을 눌렀을 때만 시작됩니다.</p></div>
    <div class="page-actions">
      <button type="button" disabled={syncing || diagnosing} onclick={() => void runSync()}>{syncing ? `${syncStageLabel(sync?.stage ?? null)} 중` : "데이터 동기화"}</button>
      <button class="button button--secondary" type="button" disabled={syncing || diagnosing} onclick={() => void runDiagnostics()}>{diagnosing ? "진단 중" : "연결 진단"}</button>
    </div>
  </div>
  {#if sync?.state === "complete"}<p class="state-message state-message--success" role="status">데이터 동기화를 완료했습니다.</p>{/if}
  {#if diagnostics?.state === "passed"}<p class="state-message state-message--success" role="status">연결 및 로컬 데이터 진단을 통과했습니다.</p>
  {:else if diagnostics?.state === "warning"}<p class="state-message state-message--warning" role="status">진단에서 확인할 항목이 발견되었습니다.</p>{/if}
  {#if actionError}<p class="state-message state-message--error" role="alert">{actionError}</p>{/if}
</section>

<section class="legacy-tools" aria-labelledby="legacy-tools-title">
  <div><span class="section-eyebrow">SPA 외부</span><h3 id="legacy-tools-title">기존 서버 도구</h3><p>현재 작업공간을 유지하고 로컬 서버 화면을 별도로 엽니다.</p></div>
  <nav class="legacy-actions" aria-label="기존 데이터 도구">
    {#each legacyTools as [label, url]}<button class="legacy-action" type="button" onclick={() => void openLegacy(url)}><span>{label}</span><small>새 창</small></button>{/each}
  </nav>
</section>
