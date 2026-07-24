<script>
  let { onRetry = () => {} } = $props();
</script>

<aside class="offline-banner" aria-live="polite">
  <span>오프라인 상태임. 저장된 작업은 유지됨.</span>
  <button type="button" onclick={onRetry}>다시 확인</button>
</aside>
