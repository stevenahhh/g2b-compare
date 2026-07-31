<script>
  import { detailsFor } from "./comparison.js";
  import ComparisonRow from "./ComparisonRow.svelte";
  let {
    document,
    remote = null,
    loading = false,
    comparisonLoading = false,
    onRemove = () => {},
    onShowTooltip = () => {},
    onHideTooltip = () => {},
  } = $props();
</script>

<section class="document-sheet" aria-label="단가 비교표">
  <div
    class="document-table-wrap"
    aria-busy={loading || comparisonLoading}
    onscroll={onHideTooltip}
  >
    <table class="document-table">
      <colgroup
        ><col class="col-sequence" /><col class="col-name" /><col
          class="col-spec"
        /><col class="col-unit" /><col
          class="col-price"
        />{#each ["A", "B", "C"] as slot}<col class="col-company" /><col
            class="col-company-spec"
          /><col class="col-id" /><col class="col-price" />{/each}<col
          class="col-note"
        /></colgroup
      ><thead
        ><tr
          ><th class="document-no-copy" rowspan="2">연번</th><th rowspan="2"
            >품명</th
          ><th rowspan="2">규격</th><th rowspan="2">단위</th><th rowspan="2"
            >적용단가</th
          ><th colspan="4">적용회사(A사)</th><th colspan="4">B사</th><th
            colspan="4">C사</th
          ><th rowspan="2">비고</th></tr
        ><tr
          ><th>적용회사</th><th>규격</th><th>물품식별번호</th><th>단가</th><th
            >회사명</th
          ><th>규격</th><th>물품식별번호</th><th>단가</th><th>회사명</th><th
            >규격</th
          ><th>물품식별번호</th><th>단가</th></tr
        ></thead
      ><tbody
        >{#each document.lines as line, index (line.id)}<ComparisonRow
            {document}
            {remote}
            {line}
            {index}
            details={detailsFor(remote, line)}
            busy={loading || comparisonLoading}
            {onRemove}
            {onShowTooltip}
            {onHideTooltip}
          />{/each}{#if document.lines.length === 0}<tr
            class="document-empty-row"><td colspan="18"></td></tr
          >{/if}</tbody
      >
    </table>
  </div>
</section>

<style>
  :global(.document-sheet) {
    margin-block-start: var(--space-4);
    border: 1px solid var(--line);
    background: var(--surface);
  }
  :global(.document-table-wrap) {
    max-block-size: calc(100dvh - 250px);
    overflow: auto;
    scrollbar-gutter: stable;
  }
  :global(.document-table) {
    min-inline-size: 2500px;
    border-collapse: separate;
    border-spacing: 0;
    table-layout: fixed;
  }
  :global(.document-table th),
  :global(.document-table td) {
    padding: var(--space-3);
    border-inline-end: 1px solid var(--line);
    border-block-end: 1px solid var(--line);
    font-size: 13px;
    line-height: 1.45;
    overflow-wrap: anywhere;
    vertical-align: middle;
  }
  :global(.document-table th) {
    position: sticky;
    z-index: 2;
    color: var(--ink);
    background: var(--surface-selected);
    font-size: 12px;
    font-weight: 700;
    text-align: center;
  }
  :global(.document-table tbody td:nth-child(1)) {
    position: sticky;
    z-index: 1;
    inset-inline-start: 0;
    background: var(--surface);
    border-inline-end: 1px solid var(--line-strong);
    box-shadow: 6px 0 8px -8px color-mix(in srgb, var(--ink) 45%, transparent);
  }
  :global(.document-table thead tr:first-child th:nth-child(1)) {
    z-index: 3;
    inset-inline-start: 0;
  }
  :global(.document-table thead tr:first-child th) {
    inset-block-start: 0;
    block-size: 44px;
  }
  :global(.document-table thead tr:nth-child(2) th) {
    inset-block-start: 44px;
    block-size: 44px;
  }
  :global(.document-table tbody tr) {
    min-block-size: 84px;
  }
  :global(.document-sequence) {
    display: grid;
    justify-items: center;
    gap: var(--space-2);
    text-align: center;
  }
  :global(.document-no-copy),
  :global(.document-no-copy *) {
    user-select: none;
  }
  :global(.document-sequence button) {
    min-block-size: 28px;
    padding: var(--space-1) var(--space-2);
    font-size: 11px;
  }
  :global(.document-center) {
    text-align: center;
  }
  :global(.document-number) {
    font-variant-numeric: tabular-nums;
    text-align: end;
    white-space: nowrap;
  }
  :global(.document-baseline) {
    background: var(--surface-subtle);
  }
  :global(.document-product-link) {
    color: var(--accent-dark);
    text-decoration: underline;
    text-underline-offset: 2px;
  }
  :global(.document-product-link:hover),
  :global(.document-product-link:focus-visible) {
    color: var(--accent);
  }
  :global(.spec-tooltip-trigger) {
    display: block;
    inline-size: 100%;
    padding: 0;
    border: 0;
    border-radius: var(--radius-compact);
    color: inherit;
    background: transparent;
    font: inherit;
    text-align: inherit;
    cursor: help;
    outline: none;
  }
  :global(.spec-tooltip-trigger:hover),
  :global(.spec-tooltip-trigger:focus-visible) {
    background: var(--focus);
  }
  :global(.document-empty-row td) {
    block-size: 72px;
  }
  :global(.document-table .loading-placeholder) {
    inline-size: 100%;
    margin-block: var(--space-1);
  }
  :global(.col-sequence) {
    inline-size: 70px;
  }
  :global(.col-name) {
    inline-size: 180px;
  }
  :global(.col-spec),
  :global(.col-company-spec) {
    inline-size: 300px;
  }
  :global(.col-unit) {
    inline-size: 70px;
  }
  :global(.col-price) {
    inline-size: 120px;
  }
  :global(.col-company) {
    inline-size: 130px;
  }
  :global(.col-id) {
    inline-size: 130px;
  }
  :global(.col-note) {
    inline-size: 120px;
  }
  @media (min-width: 900px) {
    :global(.document-sheet) {
      margin-block-start: 0;
    }
    :global(.document-table-wrap) {
      max-block-size: min(720px, calc(100dvh - 300px));
    }
  }
</style>
