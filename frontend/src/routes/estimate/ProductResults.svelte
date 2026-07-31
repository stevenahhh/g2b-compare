<script>
  import { money, productTitle } from "./formatting.js";
  let {
    items = [],
    selectedProduct = null,
    searching = false,
    disabled = false,
    onSelect = () => {},
    onAdd = () => {},
  } = $props();
  function fallback(event) {
    event.currentTarget.onerror = null;
    event.currentTarget.src = "/static/product-placeholder.svg";
  }
</script>

<div class="document-result-scroll" aria-busy={searching}>
  <div class="catalog-grid">
    {#if searching && items.length === 0}{#each [1, 2] as placeholder}<article
          class="loading-card"
          aria-hidden="true"
        >
          <span class="loading-placeholder loading-placeholder--image"></span>
          <div class="loading-card__body">
            <span class="loading-placeholder loading-placeholder--title"
            ></span><span class="loading-placeholder loading-placeholder--text"
            ></span><span class="loading-placeholder loading-placeholder--short"
            ></span>
          </div>
        </article>{/each}{/if}
    {#each items as item (item.product_id)}
      <article class="catalog-card">
        <button
          class="catalog-card__select document-result-card__body"
          type="button"
          aria-pressed={selectedProduct?.product_id === item.product_id}
          onclick={() => onSelect(item)}
          ><img
            loading="lazy"
            src={item.image_url || "/static/product-placeholder.svg"}
            alt={`${item.name} 상품 이미지`}
            onerror={fallback}
          />
          <div class="catalog-card__details">
            <strong>{productTitle(item)}</strong><span
              class="catalog-card__price"
              >{money(item.price_won)}원 / {item.unit}</span
            ><span
              >{item.contract_method} · {item.delivery_condition} · 납기 {item.delivery_days}일
              · {item.contract_end_date}</span
            >{#if item.attributes?.length}<dl class="attribute-list">
                {#each item.attributes as attribute}<div>
                    <dt>{attribute.name}</dt>
                    <dd>{attribute.value}{attribute.unit}</dd>
                  </div>{/each}
              </dl>{/if}
          </div></button
        >
        <div class="catalog-card__actions">
          <a class="g2b-link" href={item.g2b_url}>나라장터에서 보기</a><button
            class="button button--secondary"
            type="button"
            {disabled}
            onclick={() => onAdd(item)}>리스트에 추가</button
          >
        </div>
      </article>
    {/each}
  </div>
</div>

<style>
  :global(.document-result-scroll) {
    min-block-size: 0;
    overflow: auto;
    scrollbar-gutter: stable;
  }
  :global(.document-search-overlay .catalog-card) {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 112px;
    min-block-size: 0;
    block-size: auto;
    gap: var(--space-2);
    padding: var(--space-2);
    border: 1px solid var(--line);
    border-radius: var(--radius-control);
    background: var(--surface);
  }
  :global(.document-search-overlay .catalog-card + .catalog-card) {
    margin-block-start: var(--space-2);
  }
  :global(.document-search-overlay .catalog-card:hover) {
    border-color: var(--line-strong);
    background: var(--surface-subtle);
  }
  :global(.document-search-overlay .catalog-card__actions) {
    display: grid;
    grid-template-rows: repeat(2, minmax(0, 1fr));
    gap: var(--space-2);
  }
  :global(.document-search-overlay .catalog-card__actions > *) {
    inline-size: 100%;
    min-block-size: 32px;
    padding: var(--space-1) var(--space-2);
    font-size: 11px;
  }
  :global(.document-result-card__body) {
    align-self: stretch;
    align-items: center;
    cursor: default;
  }
  :global(.document-search-overlay .document-result-card__body) {
    grid-template-columns: 44px minmax(0, 1fr);
    gap: var(--space-2);
  }
  :global(.document-search-overlay .catalog-card img) {
    inline-size: 44px;
    block-size: 44px;
  }
  :global(.document-search-overlay .catalog-card__details > strong) {
    font-size: 13px;
    line-height: 1.3;
  }
  :global(.document-search-overlay .catalog-card__details > span) {
    margin-block-start: 2px;
    font-size: 11px;
    line-height: 1.3;
  }
  :global(
    .document-search-overlay .catalog-card__details > .catalog-card__price
  ) {
    margin-block-start: 3px;
    font-size: 14px;
  }
  :global(.document-search-overlay .attribute-list) {
    display: none;
  }
</style>
