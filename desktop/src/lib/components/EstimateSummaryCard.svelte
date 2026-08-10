<script lang="ts">
  import type { EstimateSummary } from "../models";

  let {
    summary,
    onOpen,
    onDelete,
  }: {
    summary: EstimateSummary;
    onOpen: (id: string) => void;
    onDelete: (id: string) => void;
  } = $props();
</script>

<article class="estimate-summary">
  <button class="estimate-summary__open" type="button" onclick={() => onOpen(summary.id)}>
    <strong>{summary.title}</strong>
    <span>{summary.line_count.toLocaleString()}개 품목 · 합계 {summary.total_won.toLocaleString()}원</span>
    <span class="estimate-summary__status">저장됨 · 리비전 {summary.revision.toLocaleString()}</span>
  </button>
  <button class="button button--secondary" type="button" onclick={() => onDelete(summary.id)}>삭제</button>
</article>
