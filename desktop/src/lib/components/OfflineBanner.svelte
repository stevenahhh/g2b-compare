<script lang="ts">
  import type { ConflictResolution, ReconciliationStatus } from "../models";

  let {
    status,
    busy = false,
    onRetry,
    onResolve,
  }: {
    status: ReconciliationStatus;
    busy?: boolean;
    onRetry: () => void;
    onResolve: (sequence: number, resolution: ConflictResolution) => void;
  } = $props();

  const headline = $derived(
    status.state === "replaying" ? "저장된 변경사항을 다시 적용하는 중"
      : status.state === "conflict" ? "동기화 충돌 확인 필요"
        : !status.online || status.state === "offline" ? "오프라인 상태"
          : "동기화 대기 중",
  );
  const detail = $derived(
    status.state === "conflict"
      ? `${status.conflicts.length.toLocaleString()}건의 변경사항이 원격 문서와 충돌했습니다.`
      : status.state === "replaying"
        ? `${status.queued_count.toLocaleString()}건을 순서대로 처리하고 있습니다.`
        : `${status.queued_count.toLocaleString()}건의 변경사항이 이 기기에 안전하게 저장되어 있습니다.`,
  );
</script>

<aside class:reconciliation-banner--conflict={status.state === "conflict"} class="reconciliation-banner" aria-live="polite">
  <div class="reconciliation-banner__summary">
    <span class:reconciliation-indicator--active={status.state === "replaying"} class="reconciliation-indicator" aria-hidden="true"></span>
    <div><strong>{headline}</strong><span>{detail}</span></div>
  </div>
  {#if status.state !== "replaying"}
    <button class="button button--secondary button--compact" type="button" disabled={busy} onclick={onRetry}>{busy ? "확인 중" : "다시 확인"}</button>
  {/if}
  {#if status.state === "conflict" && status.conflicts.length}
    <ul class="reconciliation-conflicts" aria-label="조정할 충돌">
      {#each status.conflicts as conflict (conflict.sequence)}
        <li>
          <span><strong>문서 {conflict.entity_id}</strong><small>로컬 편집본과 원격 리비전이 다릅니다.</small></span>
          <span class="reconciliation-conflicts__actions">
            <button class="button button--secondary button--compact" type="button" disabled={busy} onclick={() => onResolve(conflict.sequence, "use-remote")}>원격본 사용</button>
            <button class="button button--compact" type="button" disabled={busy} onclick={() => onResolve(conflict.sequence, "keep-local")}>로컬 변경 다시 적용</button>
          </span>
        </li>
      {/each}
    </ul>
  {/if}
</aside>
