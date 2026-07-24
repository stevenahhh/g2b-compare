<script>
  import { onMount } from "svelte";
  import { requestJson } from "../api.js";

  let { onFailure = () => {} } = $props();
  let state = $state("loading");
  let data = $state(null);
  let error = $state("");

  const counts = [
    ["업체", "company_count"],
    ["주품목", "product_count"],
    ["관계", "relation_count"],
    ["옵션 행", "option_row_count"],
    ["고유 옵션", "unique_option_count"],
    ["API 수집 대기", "pending_api_target_count"],
    ["사이트 수집 대기", "pending_site_product_count"],
  ];

  async function load() {
    state = "loading";
    error = "";
    try {
      data = await requestJson("/api/data/status");
      state = "ready";
    } catch (caught) {
      state = "error";
      error = caught.message;
      onFailure(caught);
    }
  }

  onMount(() => {
    void load();
  });
</script>

<header class="page-header">
  <h1>데이터 상태</h1>
</header>

<section
  class={`panel status-panel status-panel--${state}${state === "ready" && !data?.ready ? " status-panel--warning" : ""}`}
  aria-busy={state === "loading"}
>
  <div class="status-summary" role={state === "error" ? "alert" : "status"} aria-live="polite">
    {#if state === "loading"}
      <span class="loading-spinner" aria-hidden="true"></span>
    {:else}
      <span
        class:status-indicator--error={state === "error"}
        class:status-indicator--warning={state === "ready" && !data?.ready}
        class="status-indicator"
        aria-hidden="true"
      ></span>
    {/if}
    {#if state === "loading"}
      <div>
        <strong>데이터 확인 중</strong>
        <p class="state-message">
          {data ? "기존 수치를 유지한 채 최신 적재 상태를 확인하고 있음." : "최신 적재 상태를 불러오고 있음."}
        </p>
      </div>
    {:else if state === "error"}
      <div>
        <strong>상태 확인 실패</strong>
        <p class="state-message state-message--error">{error}{data ? " · 마지막 확인 수치는 아래에 유지함." : ""}</p>
      </div>
    {:else}
      <div>
        <strong>{data.ready ? "사용 준비됨" : "준비 확인 필요"}</strong>
        <p class="state-message">서버 상태: {data.readiness}</p>
      </div>
    {/if}
  </div>
  <button class="button" type="button" onclick={load} disabled={state === "loading"}>
    {#if state === "loading"}<span class="loading-label"><span class="loading-spinner" aria-hidden="true"></span>확인 중</span>{:else}새로고침{/if}
  </button>
</section>

{#if data || state === "loading"}
  <section class="status-counts" aria-label={state === "error" ? "마지막으로 확인된 데이터 개수" : "데이터 개수"}>
    {#each counts as [label, key]}
      <article class="panel data-count">
        <span>{label}</span>
        {#if data}
          <strong>{data[key]?.toLocaleString() ?? 0}</strong>
        {:else}
          <strong class="loading-placeholder loading-placeholder--number" aria-hidden="true"></strong>
        {/if}
      </article>
    {/each}
  </section>
{/if}

<section class="legacy-tools" aria-labelledby="legacy-tools-title">
  <div>
    <p class="legacy-tools__label">SPA 외부</p>
    <h2 id="legacy-tools-title">기존 서버 도구</h2>
    <p>현재 작업공간을 유지하고 별도 서버 화면을 새 창에서 엶.</p>
  </div>
  <nav class="legacy-actions" aria-label="기존 데이터 도구">
    <a href="/priority" target="_blank" rel="noreferrer"><span class="legacy-action__name">우선 수집</span><span>새 창</span></a>
    <a href="/sync" target="_blank" rel="noreferrer"><span class="legacy-action__name">동기화</span><span>새 창</span></a>
    <a href="/live" target="_blank" rel="noreferrer"><span class="legacy-action__name">실시간 검색</span><span>새 창</span></a>
  </nav>
</section>

<style>
  .status-panel--error {
    border-color: color-mix(in srgb, var(--danger) 28%, var(--line));
    background: color-mix(in srgb, var(--danger) 6%, var(--surface));
  }

  .status-panel--warning {
    border-color: color-mix(in srgb, var(--warning) 28%, var(--line));
    background: var(--warning-surface);
  }

  .status-summary {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    min-inline-size: 0;
  }

  .status-summary strong {
    display: block;
    margin-block-end: var(--space-1);
    font-size: 14px;
    font-weight: 600;
  }

  .status-indicator {
    flex: 0 0 auto;
    inline-size: 10px;
    block-size: 10px;
    border: 2px solid var(--surface);
    border-radius: 50%;
    background: var(--accent);
    box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 36%, var(--line));
  }

  .status-indicator--error {
    background: var(--danger);
    box-shadow: 0 0 0 1px color-mix(in srgb, var(--danger) 36%, var(--line));
  }

  .status-indicator--warning {
    background: var(--warning);
    box-shadow: 0 0 0 1px color-mix(in srgb, var(--warning) 36%, var(--line));
  }

  .data-count {
    min-block-size: 120px;
    align-content: center;
  }

  .legacy-tools__label {
    margin-block-end: var(--space-1);
    color: var(--warning);
    font-size: 11px;
    letter-spacing: 0.12em;
  }

  .legacy-actions a {
    display: inline-flex;
    align-items: baseline;
    gap: var(--space-1);
    text-decoration: none;
  }

  .legacy-actions a span {
    color: var(--muted);
    font-size: 11px;
  }

  .legacy-actions .legacy-action__name {
    color: var(--accent);
    font-size: 14px;
    text-decoration: underline;
    text-underline-offset: 3px;
  }

</style>
