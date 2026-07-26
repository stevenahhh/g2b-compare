<script>
  import { onMount } from "svelte";
  import { requestJson } from "../api.js";
  import Modal from "../components/Modal.svelte";
  import { deleteEstimate, getAllEstimates, getAppState, putAppState, putEstimate, putSyncedEstimate } from "../lib/db.js";
  import { syncPendingEstimates } from "../lib/sync.js";

  let { revision = 0, onNavigate = () => {}, onFailure = () => {} } = $props();
  let records = $state([]);
  let error = $state("");
  let deleting = $state(null);
  let loading = $state(true);
  let creating = $state(false);
  let syncing = $state(false);
  function id() { return [...crypto.getRandomValues(new Uint8Array(16))].map((value) => value.toString(16).padStart(2, "0")).join(""); }
  function titleFor(sequence) { const now = new Date(); const day = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}${String(now.getDate()).padStart(2, "0")}`; const time = `${String(now.getHours()).padStart(2, "0")}${String(now.getMinutes()).padStart(2, "0")}${String(now.getSeconds()).padStart(2, "0")}`; return `${sequence}-${day}-${time}`; }
  function localDocument(serverDocument) {
    return {
      id: serverDocument.id,
      title: serverDocument.title,
      created_at: serverDocument.created_at,
      updated_at: serverDocument.updated_at,
      lines: serverDocument.lines.map(({ id, line_kind, product_id, parent_product_id, relation_id, offer_operation, offer_key, item_name_snapshot, spec_snapshot, company_snapshot, unit_snapshot, unit_price_won_snapshot, quantity }) => ({ id, line_kind, product_id, parent_product_id, relation_id, offer_operation, offer_key, item_name_snapshot, spec_snapshot, company_snapshot, unit_snapshot, unit_price_won_snapshot, quantity: String(quantity) })),
    };
  }
  async function refresh() {
    const local = await getAllEstimates();
    const localById = new Map(local.map((record) => [record.id, record]));
    let remote = [];
    try { remote = await requestJson("/api/estimates"); }
    catch (caught) { onFailure(caught); error = "서버 목록을 불러오지 못해 이 기기의 저장본을 표시함."; }
    const hydrated = await Promise.all(remote.map(async (summary) => {
      const stored = localById.get(summary.id);
      if (stored?.pendingSync || stored?.deleted) return stored;
      try {
        const document = localDocument(await requestJson(`/api/estimates/${summary.id}`));
        await putSyncedEstimate(document);
        return { id: summary.id, document, pendingSync: false, deleted: false, error: null };
      }
      catch (caught) { onFailure(caught); return stored ?? null; }
    }));
    records = [...local.filter((record) => !record.deleted && !remote.some((summary) => summary.id === record.id)), ...hydrated].filter((record) => record && !record.deleted && record.document.lines.length).sort((left, right) => String(right.document.updated_at ?? "").localeCompare(String(left.document.updated_at ?? "")));
    loading = false;
  }
  async function create() { if (creating) return; creating = true; const estimateId = id(); const count = (await getAllEstimates()).filter((record) => !record.deleted && record.document.lines.length).length; await putEstimate({ id: estimateId, title: titleFor(count + 1), lines: [] }); await putAppState("activeEstimateId", estimateId); onNavigate(`/estimates/${estimateId}`); }
  async function remove() { const estimateId = deleting; deleting = null; if (!estimateId) return; await deleteEstimate(estimateId); if ((await getAppState("activeEstimateId")) === estimateId) await putAppState("activeEstimateId", null); await refresh(); void syncPendingEstimates().then(refresh); }
  async function retry() { if (syncing) return; syncing = true; error = ""; try { await syncPendingEstimates(); await refresh(); } finally { syncing = false; } }
  async function open(estimateId) { await putAppState("activeEstimateId", estimateId); onNavigate(`/estimates/${estimateId}`); }
  onMount(() => { void refresh(); });
  $effect(() => { revision; if (!loading) void refresh(); });
</script>
<header class="page-header">
  <h1>문서 작성</h1>
</header>
<div class="page-actions">
  <button type="button" onclick={create} disabled={creating}>
    {#if creating}<span class="loading-label"><span class="loading-spinner" aria-hidden="true"></span>새 내역 여는 중</span>{:else}새 내역 시작{/if}
  </button>
  <button class="button--secondary" type="button" onclick={retry} disabled={syncing}>
    {#if syncing}<span class="loading-label"><span class="loading-spinner" aria-hidden="true"></span>동기화 중</span>{:else}동기화 재시도{/if}
  </button>
</div>
{#if error}<p class="state-message state-message--error" role="status">{error}</p>{/if}
{#if loading}
  <section class="empty-state estimate-state" aria-busy="true">
    <h2 class="loading-label"><span class="loading-spinner" aria-hidden="true"></span>저장된 내역 확인 중</h2>
    <div class="loading-stack" aria-hidden="true">
      <span class="loading-placeholder loading-placeholder--title"></span>
      <span class="loading-placeholder loading-placeholder--text"></span>
      <span class="loading-placeholder loading-placeholder--short"></span>
    </div>
  </section>
{:else if records.length}
  <section class="estimate-list" aria-label="저장된 문서">
    {#each records as record (record.id)}
      <article class="estimate-summary">
        <button class="estimate-summary__open" type="button" onclick={() => open(record.id)}>
          <strong>{record.document.title}</strong>
          <span>{record.document.lines.length}개 품목 · {record.pendingSync ? "동기화 대기" : "동기화됨"}</span>
          {#if record.error}<span class="state-message--error">동기화 오류: {record.error}</span>{/if}
        </button>
        <button class="button--secondary" type="button" onclick={() => deleting = record.id}>삭제</button>
      </article>
    {/each}
  </section>
{:else}
  <section class="empty-state estimate-state"><h2>저장된 내역 없음</h2><p>새 내역을 시작하거나 검색 화면에서 품목을 추가하세요.</p></section>
{/if}
{#if deleting}
  <Modal open kind="confirm" title="문서 삭제" message="이 문서를 삭제할까요? 연결이 복구되면 삭제 상태가 서버에도 반영됨." confirmLabel="삭제" onConfirm={remove} onCancel={() => deleting = null} />
{/if}

<style>
  .estimate-state { margin-block-start: var(--space-3); }
</style>
