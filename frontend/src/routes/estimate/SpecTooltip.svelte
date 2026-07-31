<script>
  let { tooltip = null } = $props();
</script>

{#if tooltip}<aside
    id="full-spec-tooltip"
    class="spec-tooltip"
    class:spec-tooltip--above={tooltip.above}
    style={`inset-inline-start: ${tooltip.left}px; inset-block-start: ${tooltip.top}px;`}
    role="tooltip"
  >
    <p class="spec-tooltip__title">전체 규격</p>
    <p>{tooltip.spec}</p>
    {#if tooltip.attributes?.length}<dl>
        {#each tooltip.attributes as attribute}<div>
            <dt>{attribute.name}</dt>
            <dd>{attribute.value}{attribute.unit}</dd>
          </div>{/each}
      </dl>{/if}
  </aside>{/if}

<style>
  :global(.spec-tooltip) {
    position: fixed;
    z-index: 30;
    inline-size: min(32rem, calc(100vw - var(--space-4)));
    max-block-size: min(20rem, calc(100dvh - var(--space-4)));
    overflow: auto;
    padding: var(--space-3);
    border: 1px solid var(--line);
    border-radius: var(--radius-control);
    color: var(--ink);
    background: var(--surface);
    box-shadow: 0 var(--space-2) var(--space-6)
      color-mix(in srgb, var(--ink) 14%, transparent);
    font-size: 13px;
    line-height: 1.55;
    pointer-events: none;
  }
  :global(.spec-tooltip--above) {
    transform: translateY(-100%);
  }
  :global(.spec-tooltip p) {
    margin: 0;
  }
  :global(.spec-tooltip__title) {
    margin-block-end: var(--space-2);
    color: var(--accent-dark);
  }
  :global(.spec-tooltip dl) {
    display: grid;
    gap: var(--space-2);
    margin: var(--space-3) 0 0;
    padding-block-start: var(--space-3);
    border-block-start: 1px solid var(--line);
  }
  :global(.spec-tooltip dl div) {
    display: grid;
    grid-template-columns: 92px minmax(0, 1fr);
    gap: var(--space-3);
  }
  :global(.spec-tooltip dt) {
    color: var(--muted);
  }
  :global(.spec-tooltip dd) {
    margin: 0;
  }
</style>
