<script>
  import { onDestroy } from "svelte";
  let {
    id,
    exportReady = false,
    comparisonLoading = false,
    refreshStatus = "",
    refreshDisabled = false,
    onNavigate = () => {},
    onCopyTable = () => "",
    onRefresh = () => {},
  } = $props();
  let copyStatus = $state("");
  let copyTimer;
  async function copyTable(event) {
    const button = event.currentTarget;
    copyStatus = "";
    let buffer;
    try {
      const text = onCopyTable();
      if (globalThis.navigator.clipboard?.writeText)
        await globalThis.navigator.clipboard.writeText(text);
      else {
        buffer = Object.assign(globalThis.document.createElement("textarea"), {
          value: text,
          className: "visually-hidden",
        });
        globalThis.document.body.append(buffer);
        buffer.select();
        if (!globalThis.document.execCommand("copy"))
          throw new Error("copy failed");
      }
      copyStatus = "복사됨";
    } catch {
      copyStatus = "복사 실패";
    } finally {
      buffer?.remove();
      button.focus();
      clearTimeout(copyTimer);
      copyTimer = setTimeout(() => (copyStatus = ""), 1600);
    }
  }
  function openProductSearch() {
    globalThis.requestAnimationFrame(() => {
      const search = globalThis.document.getElementById(
        "document-product-search",
      );
      search?.focus();
      search?.click();
    });
  }
  onDestroy(() => clearTimeout(copyTimer));
</script>

<section class="page-actions">
  <button
    class="button--secondary document-back"
    type="button"
    onclick={() => onNavigate("/estimates")}>닫기</button
  >
  <button
    class="button"
    type="button"
    onclick={openProductSearch}
    disabled={comparisonLoading}
    >내역 추가</button
  >
  <button class="button" type="button" onclick={copyTable}
    >{copyStatus || "표 복사"}</button
  >
  {#if exportReady}<a
      class="button button--secondary"
      href={`/estimates/${id}/export.xlsx`}>XLSX 내려받기</a
    >{/if}
  <button
    class="button--secondary comparison-refresh"
    type="button"
    onclick={onRefresh}
    disabled={refreshDisabled || comparisonLoading}
    aria-busy={comparisonLoading}
  >
    {#if comparisonLoading}<span class="loading-label"
        ><span class="loading-spinner" aria-hidden="true"></span>새로고침 중</span
      >{:else if refreshStatus}새로고침 완료{:else}비교군 새로고침{/if}
  </button>
</section>

<style>
  :global(.document-back) {
    margin-inline-end: auto;
  }
  @media (max-width: 640px) {
    :global(.comparison-refresh) {
      grid-column: 1 / -1;
    }
  }
</style>
