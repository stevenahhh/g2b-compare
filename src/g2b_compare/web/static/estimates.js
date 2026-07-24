(() => {
  const dialog = document.querySelector("[data-delete-dialog]");
  const form = document.querySelector("[data-delete-form]");
  const name = document.querySelector("[data-delete-name]");
  if (!dialog || !form || !name) return;

  document.querySelectorAll("[data-delete-estimate]").forEach((button) => {
    button.addEventListener("click", () => {
      const estimateId = button.dataset.deleteEstimate;
      if (!estimateId) return;
      name.textContent = button.dataset.deleteTitle || "선택한 관급내역";
      form.action = `/estimates/${encodeURIComponent(estimateId)}/delete`;
      dialog.showModal();
    });
  });

  document.querySelector("[data-delete-cancel]")?.addEventListener("click", () => {
    dialog.close();
  });
})();
