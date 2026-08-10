<script lang="ts">
  import { tick } from "svelte";

  let {
    title,
    disabled = false,
    onCommit,
  }: {
    title: string;
    disabled?: boolean;
    onCommit: (title: string) => void;
  } = $props();

  let editing = $state(false);
  let draft = $state("");
  let cancelled = false;
  let input = $state<HTMLInputElement>();

  async function start() {
    if (disabled) return;
    draft = title;
    cancelled = false;
    editing = true;
    await tick();
    input?.focus();
    input?.select();
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

  function keydown(event: KeyboardEvent) {
    if (event.key === "Enter") (event.currentTarget as HTMLInputElement).blur();
    if (event.key === "Escape") {
      event.preventDefault();
      cancelled = true;
      editing = false;
    }
  }
</script>

{#if disabled}
  <h2>{title}</h2>
{:else if editing}
  <input class="estimate-title-input" aria-label="문서 제목" bind:this={input} bind:value={draft} onblur={commit} onkeydown={keydown} />
{:else}
  <button class="estimate-title-button" type="button" aria-label={`문서 제목 편집: ${title}`} onclick={() => void start()}><h2>{title}</h2></button>
{/if}
