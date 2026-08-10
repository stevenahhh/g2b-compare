<script lang="ts">
  import { onMount } from "svelte";

  import ConfirmModal from "../lib/components/ConfirmModal.svelte";
  import EstimateComparisonTable from "../lib/components/EstimateComparisonTable.svelte";
  import EstimateDocumentActions from "../lib/components/EstimateDocumentActions.svelte";
  import EstimateProductPicker from "../lib/components/EstimateProductPicker.svelte";
  import EstimateTitleEditor from "../lib/components/EstimateTitleEditor.svelte";
  import type { EstimateChangeEvent } from "../lib/estimateEvents";
  import type { DesktopClient } from "../lib/invoke";
  import type {
    CatalogProduct,
    CatalogRelation,
    EstimateDocument,
    EstimateLine,
    EstimateLineInput,
    UpdateEstimateRequest,
  } from "../lib/models";
  import { createTransientFeedbackDeadline } from "../lib/transientFeedback";

  let {
    id,
    client,
    onNavigate,
    onReconciliation = () => undefined,
    createId = randomId,
    externalChange = null,
    estimateChangeVersion = 0,
  }: {
    id: string;
    client: DesktopClient;
    onNavigate: (path: string) => void;
    onReconciliation?: () => void;
    createId?: () => string;
    externalChange?: EstimateChangeEvent | null;
    estimateChangeVersion?: number;
  } = $props();

  let document = $state<EstimateDocument | null>(null);
  let loading = $state(true);
  let saving = $state(false);
  let refreshing = $state(false);
  let refreshStatus = $state("");
  let actionError = $state("");
  let saveError = $state("");
  let dirty = $state(false);
  let conflict = $state(false);
  let deleting = $state(false);
  let error = $state("");
  let loadVersion = 0;
  let saveGeneration = 0;
  let editVersion = 0;
  let savedEditVersion = 0;
  let saveLoop: Promise<void> | null = null;
  let handledChangeVersion = 0;
  let disposed = false;
  const actionFeedbackDeadline = createTransientFeedbackDeadline(() => {
    refreshStatus = "";
    actionError = "";
  });

  const total = $derived(
    document?.lines.reduce(
      (sum, line) => sum + (
        line.comparisons.find((item) => item.slot === "A")?.price_won_snapshot
          ?? line.unit_price_won_snapshot
      ),
      0,
    ) ?? 0,
  );

  function randomId(): string {
    return [...crypto.getRandomValues(new Uint8Array(16))]
      .map((value) => value.toString(16).padStart(2, "0"))
      .join("");
  }

  function message(caught: unknown): string {
    return caught instanceof Error ? caught.message : String(caught);
  }

  function isRevisionConflict(caught: unknown): boolean {
    if (typeof caught === "object" && caught !== null && "code" in caught) {
      return String((caught as { code: unknown }).code).toLowerCase() === "revision_conflict";
    }
    return /revision conflict|리비전 충돌/i.test(message(caught));
  }

  function invalidatePendingLoads(): number {
    loadVersion += 1;
    return loadVersion;
  }

  function isCurrentLoad(requestVersion: number, estimateId: string): boolean {
    return !disposed && requestVersion === loadVersion && estimateId === id;
  }

  async function load() {
    const requestVersion = invalidatePendingLoads();
    const generation = ++saveGeneration;
    const estimateId = id;
    saveLoop = null;
    saving = false;
    loading = true;
    error = "";
    try {
      const loaded = await client.readEstimate(estimateId);
      if (!isCurrentLoad(requestVersion, estimateId) || generation !== saveGeneration) return;
      document = loaded;
      editVersion = 0;
      savedEditVersion = 0;
      dirty = false;
      saveError = "";
      conflict = false;
      void client.saveEstimateView({ active_estimate_id: estimateId }).catch(() => {
        // View persistence must not replace a successfully loaded document with an error state.
      });
    } catch (caught) {
      if (!isCurrentLoad(requestVersion, estimateId) || generation !== saveGeneration) return;
      document = null;
      error = message(caught);
    } finally {
      if (isCurrentLoad(requestVersion, estimateId) && generation === saveGeneration) loading = false;
    }
  }

  function lineInput(line: EstimateLine): EstimateLineInput {
    const { line_no: _lineNo, comparisons: _comparisons, ...input } = line;
    return input;
  }

  function requestFor(value: EstimateDocument): UpdateEstimateRequest {
    return {
      expected_revision: value.revision,
      title: value.title,
      lines: value.lines.map(lineInput),
      comparisons: value.lines.flatMap((line) => line.comparisons),
    };
  }

  async function refreshComparisons() {
    if (!document || saving || refreshing || dirty || document.lines.length === 0) return;
    const operationVersion = invalidatePendingLoads();
    const estimateId = document.id;
    const request = { expected_revision: document.revision };
    refreshing = true;
    actionFeedbackDeadline.cancel();
    refreshStatus = "";
    actionError = "";
    error = "";
    conflict = false;
    try {
      const refreshed = await client.refreshEstimateComparisons(estimateId, request);
      if (!isCurrentLoad(operationVersion, estimateId)) return;
      document = refreshed;
      refreshStatus = "새로고침 완료";
      actionFeedbackDeadline.reset();
    } catch (caught) {
      if (!isCurrentLoad(operationVersion, estimateId)) return;
      if (isRevisionConflict(caught)) {
        conflict = true;
      } else {
        actionError = message(caught);
        actionFeedbackDeadline.reset();
      }
    } finally {
      refreshing = false;
    }
  }

  function isCurrentSave(generation: number, estimateId: string): boolean {
    return !disposed
      && generation === saveGeneration
      && estimateId === id
      && document?.id === estimateId;
  }

  function startSave() {
    if (!document || !dirty || refreshing || disposed || saveLoop) return;
    saveLoop = persistPendingChanges(saveGeneration);
  }

  async function persistPendingChanges(generation: number) {
    try {
      while (
        !disposed
        && generation === saveGeneration
        && document
        && savedEditVersion < editVersion
      ) {
        const snapshot = document;
        const requestVersion = editVersion;
        const estimateId = snapshot.id;
        const request = requestFor(snapshot);
        saving = true;
        actionFeedbackDeadline.cancel();
        refreshStatus = "";
        actionError = "";
        error = "";
        conflict = false;
        saveError = "";
        try {
          const saved = await client.updateEstimate(estimateId, request);
          if (!isCurrentSave(generation, estimateId)) return;
          savedEditVersion = requestVersion;
          if (editVersion === requestVersion) {
            document = saved;
          } else if (document) {
            document = { ...document, revision: saved.revision };
          }
          dirty = savedEditVersion < editVersion;
        } catch (caught) {
          if (!isCurrentSave(generation, estimateId)) return;
          dirty = true;
          if (isRevisionConflict(caught)) {
            conflict = true;
            error = "";
          } else {
            saveError = message(caught);
          }
          return;
        }
      }
    } finally {
      if (generation !== saveGeneration) return;
      saving = false;
      saveLoop = null;
      onReconciliation();
    }
  }

  function queueLocalSave() {
    editVersion += 1;
    dirty = true;
    saveError = "";
    startSave();
  }

  function openProductSearch() {
    const input = globalThis.document.getElementById("document-product-search");
    if (input instanceof HTMLInputElement) {
      input.focus();
      input.click();
    }
  }

  function commitTitle(title: string) {
    if (!document) return;
    invalidatePendingLoads();
    loading = false;
    document = { ...document, title };
    queueLocalSave();
  }

  function removeLine(lineId: string) {
    if (!document) return;
    invalidatePendingLoads();
    loading = false;
    document = {
      ...document,
      lines: document.lines
        .filter((line) => line.id !== lineId)
        .map((line, index) => ({ ...line, line_no: index + 1 })),
    };
    queueLocalSave();
  }

  function addItem(item: CatalogProduct | CatalogRelation): string {
    if (!document) return "문서를 먼저 불러와야 합니다.";
    if (document.lines.length >= 9) return "문서에는 품목을 최대 9개까지 추가할 수 있습니다.";
    const relation = "relation_id" in item ? item : null;
    if (relation && document.lines.some((line) => line.relation_id === relation.relation_id)) {
      return "이미 추가된 하위 품목입니다.";
    }
    const line: EstimateLine = {
      id: createId(),
      line_no: document.lines.length + 1,
      line_kind: relation ? "option" : "main",
      product_id: item.product_id,
      parent_product_id: relation?.parent_product_id ?? null,
      relation_id: relation?.relation_id ?? null,
      offer_operation: null,
      offer_key: null,
      item_name_snapshot: item.name,
      spec_snapshot: item.spec,
      company_snapshot: item.company_name,
      unit_snapshot: item.unit,
      unit_price_won_snapshot: item.price_won,
      quantity: "1",
      comparisons: [],
    };
    invalidatePendingLoads();
    loading = false;
    document = { ...document, lines: [...document.lines, line] };
    queueLocalSave();
    return "";
  }

  async function deleteDocument() {
    if (!document) return;
    const operationVersion = invalidatePendingLoads();
    const estimateId = document.id;
    deleting = false;
    actionFeedbackDeadline.cancel();
    refreshStatus = "";
    actionError = "";
    try {
      await client.deleteEstimate(estimateId);
      if (!isCurrentLoad(operationVersion, estimateId)) return;
      onReconciliation();
      onNavigate("/estimates");
    } catch (caught) {
      if (!isCurrentLoad(operationVersion, estimateId)) return;
      actionError = message(caught);
      actionFeedbackDeadline.reset();
      onReconciliation();
    }
  }

  function handleExternalChange(change: EstimateChangeEvent) {
    if (change.id !== id) return;
    invalidatePendingLoads();
    if (change.kind === "deleted") {
      dirty = false;
      onNavigate("/estimates");
      return;
    }
    if (change.revision !== null && document && document.revision >= change.revision) return;
    if (dirty || saving || refreshing) {
      conflict = true;
      error = "";
      return;
    }
    void load();
  }

  $effect(() => {
    if (!externalChange || estimateChangeVersion <= handledChangeVersion) return;
    handledChangeVersion = estimateChangeVersion;
    handleExternalChange(externalChange);
  });

  onMount(() => {
    void load();
    return () => {
      disposed = true;
      actionFeedbackDeadline.cancel();
      invalidatePendingLoads();
    };
  });
</script>

{#if document}
  <header class="page-header page-header--split">
    <div class="page-header__copy">
      <EstimateTitleEditor title={document.title} disabled={refreshing} onCommit={commitTitle} />
      <p>문서 ID: {document.id} · 리비전 {document.revision}</p>
    </div>
    <p class:estimate-save-state--dirty={dirty} class="estimate-save-state" aria-live="polite">
      {saving ? "저장 중" : saveError ? "저장 실패 · 다시 시도" : dirty ? "저장되지 않은 변경사항" : `저장됨 · 리비전 ${document.revision}`}
    </p>
  </header>
  <div class="estimate-toolbar">
    <button class="button button--secondary estimate-toolbar__back" type="button" onclick={() => onNavigate("/estimates")}>닫기</button>
    <button
      class="button button--secondary"
      type="button"
      disabled={refreshing}
      onclick={openProductSearch}
    >내역 추가</button>
    <button type="button" disabled={!dirty || saving || refreshing} onclick={startSave}>{saving ? "저장 중" : "저장"}</button>
    <button
      class="button button--secondary comparison-refresh"
      type="button"
      disabled={saving || refreshing || dirty || document.lines.length === 0}
      aria-busy={refreshing}
      onclick={() => void refreshComparisons()}
    >{refreshing ? "새로고침 중" : refreshStatus || "비교군 새로고침"}</button>
    <EstimateDocumentActions {document} {client} disabled={saving || refreshing || dirty} />
    <button class="button button--danger" type="button" disabled={saving || refreshing} onclick={() => deleting = true}>문서 삭제</button>
  </div>
  {#if conflict}
    <section class="estimate-conflict" role="alert">
      <p>다른 창에서 이 문서가 먼저 저장되었습니다. 현재 편집본은 유지되며, 최신본을 불러오면 현재 변경사항이 대체됩니다.</p>
      <button class="button button--secondary button--compact" type="button" onclick={() => conflict = false}>현재 편집 계속</button>
      <button class="button button--compact" type="button" onclick={() => void load()}>최신본 불러오기</button>
    </section>
  {/if}
  {#if error}<p class="state-message state-message--error" role="status">{error}</p>{/if}
  {#if saveError}<p class="state-message state-message--error" role="status">{saveError}</p>{/if}
  {#if actionError}<p class="state-message state-message--error" role="status">{actionError}</p>{/if}
  <EstimateProductPicker {client} disabled={refreshing} onAdd={addItem} />
  <EstimateComparisonTable lines={document.lines} disabled={refreshing} onRemove={removeLine} />
  {#if document.lines.length}
    <p class="estimate-total"><span>문서 합계</span><strong>{total.toLocaleString()}원</strong></p>
  {/if}
  {#if deleting}<ConfirmModal title="문서 삭제" message="이 문서를 영구적으로 삭제할까요?" confirmLabel="삭제" onConfirm={() => void deleteDocument()} onCancel={() => deleting = false} />{/if}
{:else if loading}
  <section class="empty-state" aria-busy="true"><h3>문서 불러오는 중</h3><p>저장된 품목과 비교군을 확인하고 있습니다.</p></section>
{:else}
  <section class="empty-state"><h3>문서를 불러오지 못했습니다.</h3><p>{error || "삭제되었거나 존재하지 않는 문서입니다."}</p><div class="page-actions"><button class="button button--secondary" type="button" onclick={() => onNavigate("/estimates")}>목록으로</button><button type="button" onclick={() => void load()}>다시 시도</button></div></section>
{/if}
