<script lang="ts">
  import EstimateLineEditor from "./EstimateLineEditor.svelte";
  import type { EstimateLine } from "../models";

  let tooltipDismissal = $state(0);

  let {
    lines,
    disabled = false,
    onRemove,
  }: {
    lines: EstimateLine[];
    disabled?: boolean;
    onRemove: (lineId: string) => void;
  } = $props();
</script>

<section class="document-sheet" aria-label="단가 비교표">
  <a class="document-scroll-link" href="#document-table-end">비교표 건너뛰기</a>
  <div
    class="document-table-wrap"
    role="region"
    aria-label="단가 비교표 스크롤 영역"
    onscroll={() => tooltipDismissal += 1}
  >
    <table class="document-table">
      <caption class="visually-hidden">문서 품목별 A사, B사, C사 단가 비교표</caption>
      <colgroup>
        <col class="col-sequence" />
        <col class="col-name" />
        <col class="col-spec" />
        <col class="col-unit" />
        <col class="col-price" />
        {#each ["A", "B", "C"] as slot}
          <col class="col-company" />
          <col class="col-company-spec" />
          <col class="col-id" />
          <col class="col-price" />
        {/each}
        <col class="col-note" />
      </colgroup>
      <thead>
        <tr>
          <th class="document-no-copy" rowspan="2" scope="col">연번</th>
          <th rowspan="2" scope="col">품명</th>
          <th rowspan="2" scope="col">규격</th>
          <th rowspan="2" scope="col">단위</th>
          <th rowspan="2" scope="col">적용단가</th>
          <th colspan="4" scope="colgroup">적용회사(A사)</th>
          <th colspan="4" scope="colgroup">B사</th>
          <th colspan="4" scope="colgroup">C사</th>
          <th rowspan="2" scope="col">비고</th>
        </tr>
        <tr>
          <th scope="col">적용회사</th>
          <th scope="col">규격</th>
          <th scope="col">물품식별번호</th>
          <th scope="col">단가</th>
          <th scope="col">회사명</th>
          <th scope="col">규격</th>
          <th scope="col">물품식별번호</th>
          <th scope="col">단가</th>
          <th scope="col">회사명</th>
          <th scope="col">규격</th>
          <th scope="col">물품식별번호</th>
          <th scope="col">단가</th>
        </tr>
      </thead>
      <tbody>
        {#each lines as line, index (line.id)}
          <EstimateLineEditor {line} {index} {disabled} {onRemove} {tooltipDismissal} />
        {/each}
        {#if lines.length === 0}
          <tr class="document-empty-row">
            <td colspan="18"><span class="visually-hidden">추가된 품목 없음</span></td>
          </tr>
        {/if}
      </tbody>
    </table>
  </div>
  <span id="document-table-end" class="visually-hidden" tabindex="-1">비교표 끝</span>
</section>
