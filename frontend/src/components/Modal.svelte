<script>
  let {
    open = false,
    title,
    message,
    kind = "error",
    confirmLabel = "확인",
    cancelLabel = "취소",
    returnFocus = null,
    onConfirm = () => {},
    onCancel = () => {},
  } = $props();

  let dialog = $state();
  let initialButton = $state();
  let opener;

  $effect(() => {
    if (!dialog) return;
    if (open && !dialog.open) {
      opener = returnFocus ?? document.activeElement;
      dialog.showModal();
      requestAnimationFrame(() => initialButton?.focus());
    } else if (!open && dialog.open) {
      dialog.close();
    }
  });

  function cancel(event) {
    event?.preventDefault();
    onCancel();
    restoreFocus();
  }

  function confirm() {
    onConfirm();
    restoreFocus();
  }

  function restoreFocus() {
    const target = opener;
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (target?.isConnected) target.focus();
      });
    });
  }
</script>

<dialog
  bind:this={dialog}
  class="modal"
  aria-labelledby="modal-title"
  oncancel={cancel}
  onclick={(event) => event.target === dialog && cancel(event)}
>
  <section class="modal__panel">
    <h2 id="modal-title">{title}</h2>
    <p>{message}</p>
    <div class="modal__actions">
      {#if kind === "confirm"}
        <button bind:this={initialButton} class="button button--secondary" type="button" onclick={cancel}>
          {cancelLabel}
        </button>
        <button class="button" type="button" onclick={confirm}>{confirmLabel}</button>
      {:else}
        <button bind:this={initialButton} class="button" type="button" onclick={cancel}>
          {confirmLabel}
        </button>
      {/if}
    </div>
  </section>
</dialog>
