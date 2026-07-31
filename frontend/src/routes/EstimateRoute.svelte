<script>
  import { onMount } from "svelte";
  import { requestJson } from "../api.js";
  import {
    deleteEstimate,
    discardSyncedEstimate,
    getAppState,
    getEstimate,
    putAppState,
    putEstimate,
    replaceSyncedEstimate,
    putSyncedEstimate,
  } from "../lib/db.js";
  import { syncPendingEstimates } from "../lib/sync.js";
  import { tableTsv } from "./estimate/comparison.js";
  import ComparisonTable from "./estimate/ComparisonTable.svelte";
  import DocumentActions from "./estimate/DocumentActions.svelte";
  import {
    appendDocumentLine,
    localDocument,
    removeDocumentLine,
  } from "./estimate/document.js";
  import { newId } from "./estimate/formatting.js";
  import ProductSearch from "./estimate/ProductSearch.svelte";
  import SpecTooltip from "./estimate/SpecTooltip.svelte";
  import TitleEditor from "./estimate/TitleEditor.svelte";

  let {
    id,
    revision = 0,
    onNavigate = () => {},
    onFailure = () => {},
    onSynced = () => {},
  } = $props();
  let document = $state(null);
  let remote = $state(null);
  let error = $state("");
  let loading = $state(true);
  let notFound = $state(false);
  let comparisonLoading = $state(false);
  let refreshStatus = $state("");
  let specTooltip = $state(null);
  let appliedRevision = 0;
  async function load() {
    loading = true;
    notFound = false;
    error = "";
    const local = await getEstimate(id);
    if (local?.deleted) {
      if ((await getAppState("activeEstimateId")) === id)
        await putAppState("activeEstimateId", null);
      loading = false;
      return;
    }
    document = local?.document ?? null;
    try {
      remote = await requestJson(`/api/estimates/${id}`);
      if (!local || !local.pendingSync) {
        document = localDocument(remote);
        await putSyncedEstimate($state.snapshot(document));
      }
      await putAppState("activeEstimateId", id);
    } catch (caught) {
      if (caught?.status === 404 && local)
        await putAppState("activeEstimateId", id);
      else if (caught?.status === 404) {
        document = null;
        notFound = true;
        if ((await getAppState("activeEstimateId")) === id)
          await putAppState("activeEstimateId", null);
      } else {
        onFailure(caught);
        error = document
          ? "오프라인 편집 중: 서버 비교 결과는 연결 후 표시됨."
          : "문서를 불러오지 못했음.";
      }
    } finally {
      loading = false;
    }
  }
  async function refreshRemoteProjection(expectedRevision) {
    const record = await getEstimate(id);
    if (!record || record.pendingSync || record.deleted) return;
    try {
      const refreshed = await requestJson(`/api/estimates/${id}`);
      if (revision !== expectedRevision) return;
      const refreshedDocument = localDocument(refreshed);
      const replaced = await replaceSyncedEstimate(
        record,
        $state.snapshot(refreshedDocument),
      );
      if (!replaced || revision !== expectedRevision) return;
      document = refreshedDocument;
      remote = refreshed;
    } catch (caught) {
      if (caught?.status === 404 && (await discardSyncedEstimate(id))) {
        document = null;
        remote = null;
        notFound = true;
        if ((await getAppState("activeEstimateId")) === id)
          await putAppState("activeEstimateId", null);
        return;
      }
      onFailure(caught);
    }
  }
  async function settleSync(deleted = false) {
    comparisonLoading = !deleted;
    try {
      await syncPendingEstimates(globalThis.fetch, onSynced);
      const saved = await getEstimate(id);
      if (saved?.error) {
        error = `동기화 오류: ${saved.error}`;
        onFailure({ offline: true });
        return;
      }
      if (deleted) return;
      remote = await requestJson(`/api/estimates/${id}`);
      error = "";
    } catch (caught) {
      onFailure(caught);
    } finally {
      comparisonLoading = false;
    }
  }
  async function refreshComparisons() {
    if (!document?.lines.length || comparisonLoading) return;
    const documentSnapshot = JSON.stringify($state.snapshot(document));
    comparisonLoading = true;
    error = "";
    refreshStatus = "";
    try {
      await syncPendingEstimates(globalThis.fetch, onSynced);
      const synced = await getEstimate(id);
      if (
        !synced ||
        synced.deleted ||
        synced.pendingSync ||
        synced.error ||
        JSON.stringify(synced.document) !== documentSnapshot
      ) {
        throw new Error("estimate-not-synchronized");
      }
      const refreshed = await requestJson(
        `/api/estimates/${id}/refresh-comparisons`,
        { method: "POST" },
      );
      const latest = await getEstimate(id);
      if (
        !latest ||
        latest.pendingSync ||
        JSON.stringify(latest.document) !== documentSnapshot
      ) {
        error = "편집 내용이 변경되어 비교군 결과를 적용하지 않았음.";
        return;
      }
      remote = refreshed;
      refreshStatus = "비교군을 새로고침함.";
    } catch (caught) {
      onFailure(caught);
      error = "비교군을 새로고침하지 못했음.";
    } finally {
      comparisonLoading = false;
    }
  }
  async function save() {
    if (!document || comparisonLoading) return;
    if (document.lines.length === 0) {
      await deleteEstimate(id);
      if ((await getAppState("activeEstimateId")) === id)
        await putAppState("activeEstimateId", null);
      void settleSync(true);
      return;
    }
    await putEstimate($state.snapshot(document));
    void settleSync();
  }
  function addProduct(item) {
    if (comparisonLoading) return "비교군 새로고침 중에는 수정할 수 없음.";
    const result = appendDocumentLine(document, item, newId);
    if (result.error) return result.error;
    document = result.document;
    void save();
    return "";
  }
  function remove(lineId) {
    if (comparisonLoading) return;
    document = removeDocumentLine(document, lineId);
    void save();
  }
  function commitTitle(title) {
    if (comparisonLoading) return;
    document = { ...document, title };
    void save();
  }
  function showTooltip(event, spec, attributes = []) {
    const rect = event.currentTarget.getBoundingClientRect();
    const above = rect.bottom > globalThis.innerHeight * 0.65;
    specTooltip = {
      spec,
      attributes,
      above,
      left: Math.max(8, Math.min(rect.left, globalThis.innerWidth - 520)),
      top: above ? rect.top - 8 : rect.bottom + 8,
    };
  }
  const hideTooltip = () => (specTooltip = null);
  onMount(() => {
    void load();
  });
  $effect(() => {
    const nextRevision = revision;
    if (!nextRevision || nextRevision === appliedRevision) return;
    appliedRevision = nextRevision;
    void refreshRemoteProjection(nextRevision);
  });
</script>

<header class="page-header">
  <TitleEditor
    title={document?.title ?? "문서 작성"}
    disabled={!document || comparisonLoading}
    onCommit={commitTitle}
  />
  <p class="route-id visually-hidden">문서 ID: {id}</p>
</header>
{#if document}
  <DocumentActions
    {id}
    exportReady={remote?.export_ready}
    {comparisonLoading}
    {refreshStatus}
    refreshDisabled={!document.lines.length}
    {onNavigate}
    onCopyTable={() => tableTsv(document, remote)}
    onRefresh={refreshComparisons}
  />
  {#if error}<p class="state-message state-message--error" role="status">
      {error}
    </p>{/if}
  <div class="document-workspace">
    <ProductSearch
      onAdd={addProduct}
      {onFailure}
      disabled={comparisonLoading}
    /><ComparisonTable
      {document}
      {remote}
      {loading}
      {comparisonLoading}
      onRemove={remove}
      onShowTooltip={showTooltip}
      onHideTooltip={hideTooltip}
    />
  </div>
  <SpecTooltip tooltip={specTooltip} />
{:else if loading}<section class="empty-state" aria-busy="true">
    <h2 class="loading-label">
      <span class="loading-spinner" aria-hidden="true"></span>문서 불러오는 중
    </h2>
    <div class="loading-stack" aria-hidden="true">
      <span class="loading-placeholder loading-placeholder--title"></span><span
        class="loading-placeholder loading-placeholder--text"
      ></span><span class="loading-placeholder loading-placeholder--short"
      ></span>
    </div>
  </section>
{:else if notFound}<section class="empty-state">
    <h2>문서를 찾을 수 없음</h2>
    <p>삭제되었거나 존재하지 않는 문서임.</p>
  </section>
{:else}<section class="empty-state">
    <h2>문서를 불러오지 못했음</h2>
    <p>{error || "연결을 확인한 뒤 다시 시도하세요."}</p>
  </section>{/if}

<style>
  :global(.state-message + .document-workspace) {
    margin-block-start: var(--space-2);
  }

  :global(.document-workspace) {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: var(--space-3);
  }

  @media (min-width: 900px) {
    :global(.document-catalog) {
      margin-block-start: 0;
    }
  }

  @media (max-width: 560px) {
    /* ProductSearch owns this rule after extraction. The literal selector is
       retained for the route-level responsive contract:
       .document-catalog .catalog-controls { grid-template-columns: 1fr; } */
    :global(.document-catalog .catalog-controls) {
      grid-template-columns: 1fr;
    }
  }
</style>
