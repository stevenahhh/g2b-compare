const root = document.querySelector("[data-estimate-id]");
const confirmDialog = document.querySelector("[data-confirm-dialog]");

const confirmDelete = () => new Promise((resolve) => {
  if (!confirmDialog) {
    resolve(false);
    return;
  }
  const settle = (confirmed) => {
    confirmDialog.removeEventListener("close", onClose);
    confirmDialog.querySelector('[value="confirm"]')?.removeEventListener("click", onConfirm);
    resolve(confirmed);
  };
  const onClose = () => settle(confirmDialog.returnValue === "confirm");
  const onConfirm = () => settle(true);
  confirmDialog.returnValue = "cancel";
  confirmDialog.addEventListener("close", onClose);
  confirmDialog.querySelector('[value="confirm"]')?.addEventListener("click", onConfirm);
  confirmDialog.showModal();
});

const encodeTsvCell = (value) => {
  const normalized = String(value ?? "").replace(/[\t\r\n]+/g, " ");
  return /^\s*[=+\-@]/.test(normalized) ? `'${normalized}` : normalized;
};
globalThis.g2bEncodeTsvCell = encodeTsvCell;

if (root) {
  const estimateId = root.dataset.estimateId;
  for (const row of root.querySelectorAll("[data-line-id]")) {
    const lineId = row.dataset.lineId;
    const quantity = row.querySelector(".quantity-input");
    let timer;
    let saveChain = Promise.resolve();
    let saveController;
    let saveVersion = 0;
    quantity?.addEventListener("input", () => {
      const amount = row.querySelector(".line-amount");
      const total = Number(quantity.value) * Number(row.dataset.unitPrice);
      if (amount && Number.isFinite(total)) {
        amount.textContent = new Intl.NumberFormat("ko-KR").format(total);
        amount.dataset.copyValue = String(total);
      }
      const version = ++saveVersion;
      window.clearTimeout(timer);
      saveController?.abort();
      timer = window.setTimeout(() => {
        const savedQuantity = quantity.value;
        saveChain = saveChain.then(async () => {
          if (version !== saveVersion) return;
          const controller = new AbortController();
          saveController = controller;
          root.querySelector(".save-state").textContent = "저장 중";
          try {
            const response = await fetch(`/estimates/${estimateId}/lines/${lineId}`, {
              method: "PATCH",
              headers: { "content-type": "application/json" },
              body: JSON.stringify({ quantity: savedQuantity }),
              signal: controller.signal,
            });
            if (version === saveVersion) {
              root.querySelector(".save-state").textContent = response.ok ? "저장됨" : "저장 실패 · 다시 시도";
            }
          } catch {
            if (version === saveVersion && !controller.signal.aborted) {
              root.querySelector(".save-state").textContent = "저장 실패 · 다시 시도";
            }
          } finally {
            if (saveController === controller) saveController = undefined;
          }
        });
      }, 500);
    });
    row.querySelector(".delete-line")?.addEventListener("click", async () => {
      if (!await confirmDelete()) return;
      const response = await fetch(`/estimates/${estimateId}/lines/${lineId}`, { method: "DELETE" });
      if (response.ok) window.location.reload();
    });
  }

  root.querySelector("[data-copy-estimate]")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const headers = [
      "연번", "본품/옵션 경로", "품명", "규격", "단위", "수량", "적용 단가", "금액", "G2B식별번호", "업체명",
      "A사 업체", "A사 규격", "A사 식별번호", "A사 단가",
      "B사 업체", "B사 규격", "B사 식별번호", "B사 단가",
      "C사 업체", "C사 규격", "C사 식별번호", "C사 단가",
    ];
    const lines = [headers.map(encodeTsvCell).join("\t")];
    for (const row of root.querySelectorAll("tr[data-line-id]")) {
      const values = [...row.querySelectorAll("[data-copy-value]")].map((cell) => cell.dataset.copyValue);
      const quantity = row.querySelector("[data-copy-input]");
      values.splice(5, 0, quantity?.value ?? "");
      const comparisonRow = row.nextElementSibling;
      for (const item of comparisonRow?.querySelectorAll("[data-comparison]") ?? []) {
        values.push(item.dataset.company, item.dataset.spec, item.dataset.productId, item.dataset.price);
      }
      while (values.length < headers.length) values.push("");
      lines.push(values.map(encodeTsvCell).join("\t"));
    }
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      button.textContent = "복사됨 · Excel에서 붙여넣기";
    } catch {
      button.textContent = "복사 실패 · 다시 시도";
    }
  });
}
