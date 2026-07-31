<script>
  import { money, optionGroup, OPTION_GROUPS } from "./formatting.js";
  let {
    selectedProduct,
    items = [],
    loading = false,
    disabled = false,
    onClose = () => {},
    onAdd = () => {},
  } = $props();
  const options = (group) =>
    items.filter((item) => optionGroup(item) === group);
  function fallback(event) {
    event.currentTarget.onerror = null;
    event.currentTarget.src = "/static/product-placeholder.svg";
  }
</script>

<aside class="document-option-panel" aria-label="연결된 하위 품목">
  <header class="document-option-panel__header">
    <div>
      <span>선택한 본품</span>
      <h2>{selectedProduct.name} · {selectedProduct.product_id}</h2>
    </div>
    <button class="button--secondary" type="button" onclick={onClose}
      >닫기</button
    >
  </header>
  <div class="document-option-groups">
    {#each OPTION_GROUPS as [group, label]}{@const groupOptions =
        options(group)}
      <section class="document-option-group">
        <h3>{label} <span>{groupOptions.length.toLocaleString()}건</span></h3>
        <div class="document-option-scroll" aria-busy={loading}>
          {#if loading}<p class="option-loading">
              <span class="loading-spinner" aria-hidden="true"></span>불러오는
              중
            </p>{:else if groupOptions.length === 0}<p class="option-empty">
              연결된 품목 없음.
            </p>{:else}{#each groupOptions as item (item.relation_id)}<article
                class="document-option-row"
              >
                <img
                  loading="lazy"
                  src={item.image_url || "/static/product-placeholder.svg"}
                  alt={`${item.name} 상품 이미지`}
                  onerror={fallback}
                />
                <div>
                  <strong>{item.name}</strong><span>{item.spec}</span><span
                    class="option-row__price"
                    >{money(item.price_won)}원 / {item.unit}</span
                  >
                </div>
                <div class="catalog-card__actions">
                  <a class="g2b-link" href={item.g2b_url}>나라장터에서 보기</a
                  ><button
                    class="button button--secondary"
                    type="button"
                    {disabled}
                    onclick={() => onAdd(item)}>리스트에 추가</button
                  >
                </div>
              </article>{/each}{/if}
        </div>
      </section>{/each}
  </div>
</aside>

<style>
  :global(.document-option-panel) {
    display: grid;
    min-block-size: 0;
    grid-template-rows: auto minmax(0, 1fr);
    overflow: hidden;
    border: 1px solid var(--line);
    border-radius: var(--radius-control);
    background: var(--surface);
  }
  :global(.document-option-panel__header) {
    display: flex;
    min-inline-size: 0;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border-block-end: 1px solid var(--line);
    background: var(--surface-subtle);
  }
  :global(.document-option-panel__header span),
  :global(.document-option-panel__header h2) {
    display: block;
    margin: 0;
  }
  :global(.document-option-panel__header span) {
    color: var(--muted);
    font-size: 11px;
  }
  :global(.document-option-panel__header h2) {
    overflow: hidden;
    font-size: 13px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  :global(.document-option-panel__header button) {
    min-block-size: 32px;
    padding-inline: var(--space-2);
    font-size: 11px;
  }
  :global(.document-option-groups) {
    display: grid;
    min-block-size: 0;
    grid-template-rows: repeat(3, minmax(0, 1fr));
  }
  :global(.document-option-group) {
    display: grid;
    min-block-size: 0;
    grid-template-rows: auto minmax(0, 1fr);
  }
  :global(.document-option-group + .document-option-group) {
    border-block-start: 1px solid var(--line);
  }
  :global(.document-option-group h3) {
    margin: 0;
    padding: var(--space-2) var(--space-3);
    font-size: 12px;
  }
  :global(.document-option-group h3 span) {
    color: var(--muted);
    font-weight: 400;
  }
  :global(.document-option-scroll) {
    min-block-size: 0;
    overflow: auto;
  }
  :global(.document-option-row) {
    display: grid;
    grid-template-columns: 36px minmax(0, 1fr) 94px;
    align-items: center;
    gap: var(--space-2);
    min-block-size: 76px;
    padding: var(--space-2) var(--space-3);
  }
  :global(.document-option-row + .document-option-row) {
    border-block-start: 1px solid var(--line);
  }
  :global(.document-option-row img) {
    inline-size: 36px;
    block-size: 36px;
    object-fit: contain;
    background: var(--canvas);
  }
  :global(.document-option-row > div:nth-child(2)) {
    min-inline-size: 0;
  }
  :global(.document-option-row strong),
  :global(.document-option-row span) {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  :global(.document-option-row strong) {
    font-size: 12px;
  }
  :global(.document-option-row span) {
    margin-block-start: 2px;
    color: var(--muted);
    font-size: 10px;
  }
  :global(.document-option-row .option-row__price) {
    color: var(--ink);
    font-size: 11px;
    font-weight: 700;
  }
  :global(.document-option-row .catalog-card__actions) {
    gap: var(--space-1);
  }
  :global(.document-option-row .catalog-card__actions > *) {
    min-block-size: 28px;
    padding: var(--space-1);
    font-size: 10px;
  }
</style>
