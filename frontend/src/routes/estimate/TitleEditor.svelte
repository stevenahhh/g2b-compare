<script>
  import { tick } from "svelte";
  import { titleKeyAction } from "./keyboard.js";
  let { title, disabled = false, onCommit = () => {} } = $props();
  let editing = $state(false);
  let draft = $state("");
  let cancelled = false;
  let titleInput = $state();
  async function start() {
    draft = title;
    cancelled = false;
    editing = true;
    await tick();
    titleInput?.focus();
    titleInput?.select();
  }
  function commit() {
    if (cancelled) {
      cancelled = false;
      return;
    }
    const next = draft.trim();
    editing = false;
    if (next && next !== title) onCommit(next);
  }
  function keydown(event) {
    const action = titleKeyAction(event.key);
    if (action === "commit") event.currentTarget.blur();
    if (action === "cancel") {
      event.preventDefault();
      cancelled = true;
      editing = false;
    }
  }
</script>

{#if disabled}
  <h1>{title}</h1>
{:else if editing}
  <input
    class="page-title-input"
    type="text"
    bind:this={titleInput}
    bind:value={draft}
    onblur={commit}
    onkeydown={keydown}
    aria-label="문서 제목"
  />
{:else}
  <button
    class="page-title-edit"
    type="button"
    onclick={start}
    aria-label={`문서 제목 편집: ${title}`}
    ><h1>{title}</h1></button
  >
{/if}

<style>
  :global(.page-title-edit) {
    all: unset;
    display: inline-block;
    cursor: text;
    border-radius: var(--radius-2, 6px);
    padding-inline: var(--space-1, 4px);
  }
  :global(.page-title-edit:hover),
  :global(.page-title-edit:focus-visible) {
    outline: 2px solid var(--color-border-focus, #94a3b8);
    outline-offset: 2px;
  }
  :global(.page-title-input) {
    width: 100%;
    max-width: 32rem;
    padding: 0;
    border: 0;
    border-bottom: 2px solid var(--color-border-focus, #94a3b8);
    color: inherit;
    background: transparent;
    font: inherit;
    font-size: 1.5rem;
    font-weight: 700;
    line-height: 1.2;
  }
  :global(.page-title-input:focus) {
    outline: none;
  }
</style>
