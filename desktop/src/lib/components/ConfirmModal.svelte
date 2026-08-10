<script lang="ts">
  import { onMount } from "svelte";

  let {
    title,
    message,
    confirmLabel = "확인",
    cancelLabel = "취소",
    destructive = true,
    onConfirm,
    onCancel,
  }: {
    title: string;
    message: string;
    confirmLabel?: string;
    cancelLabel?: string;
    destructive?: boolean;
    onConfirm: () => void;
    onCancel: () => void;
  } = $props();

  let panel: HTMLDivElement;
  let cancelButton: HTMLButtonElement;
  let restoreFocus: HTMLElement | null = null;

  function focusableElements(): HTMLElement[] {
    return Array.from(panel.querySelectorAll<HTMLElement>("button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex='-1'])"));
  }

  function keydown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      event.preventDefault();
      onCancel();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = focusableElements();
    if (focusable.length === 0) {
      event.preventDefault();
      panel.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable.at(-1) ?? first;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    } else if (!panel.contains(document.activeElement)) {
      event.preventDefault();
      first.focus();
    }
  }

  onMount(() => {
    restoreFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    queueMicrotask(() => cancelButton.focus());
    return () => {
      if (restoreFocus?.isConnected) restoreFocus.focus();
    };
  });
</script>

<svelte:window onkeydown={keydown} />
<div class="modal-backdrop" role="presentation" onclick={(event) => event.target === event.currentTarget && onCancel()}>
  <div bind:this={panel} class="modal-panel" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-message" tabindex="-1">
    <h2 id="confirm-title">{title}</h2>
    <p id="confirm-message">{message}</p>
    <div class="modal-actions">
      <button bind:this={cancelButton} class="button button--secondary" type="button" onclick={onCancel}>{cancelLabel}</button>
      <button class:button--danger={destructive} class="button" type="button" onclick={onConfirm}>{confirmLabel}</button>
    </div>
  </div>
</div>
