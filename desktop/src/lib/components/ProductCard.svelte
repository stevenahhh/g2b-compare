<script lang="ts">
  import placeholderImage from "../../assets/product-placeholder.svg";
  import { productTitle } from "../catalog";
  import type { CatalogProduct } from "../models";

  let {
    item,
    selected = false,
    compact = false,
    onSelect = undefined,
    onAdd,
    onOpen,
  }: {
    item: CatalogProduct;
    selected?: boolean;
    compact?: boolean;
    onSelect?: (item: CatalogProduct) => void;
    onAdd: (item: CatalogProduct) => void;
    onOpen: (item: CatalogProduct) => void;
  } = $props();

  function imageFailed(event: Event) {
    const image = event.currentTarget as HTMLImageElement;
    image.onerror = null;
    image.src = placeholderImage;
  }
</script>

<article class:catalog-card--selected={selected} class:catalog-card--compact={compact} class="catalog-card">
  {#if onSelect}
    <button
      class="catalog-card__select"
      type="button"
      aria-pressed={selected}
      onclick={() => onSelect?.(item)}
    >
      <img src={item.image_url || placeholderImage} alt={`${item.name} 상품 이미지`} onerror={imageFailed} />
      <div class="catalog-card__details">
        <strong>{productTitle(item)}</strong>
        <span class="catalog-card__spec">규격 · {item.spec || "수집된 규격 없음"}</span>
        <span class="catalog-card__price">{item.price_won.toLocaleString()}원 / {item.unit}</span>
        <span>{item.contract_method} · {item.delivery_condition} · 납기 {item.delivery_days}일 · {item.contract_end_date}</span>
        {#if item.attributes?.length}
          <dl class="attribute-list">
            {#each item.attributes as attribute}
              <div><dt>{attribute.name}</dt><dd>{attribute.value}{attribute.unit ?? ""}</dd></div>
            {/each}
          </dl>
        {/if}
      </div>
    </button>
  {:else}
    <img src={item.image_url || placeholderImage} alt={`${item.name} 상품 이미지`} onerror={imageFailed} />
    <div class="catalog-card__details">
      <strong>{item.name}</strong>
      <span class="catalog-card__spec">규격 · {item.spec || "수집된 규격 없음"}</span>
      <span class="catalog-card__price">{item.price_won.toLocaleString()}원 / {item.unit}</span>
    </div>
  {/if}
  <div class="catalog-card__actions">
    <button class="g2b-link" type="button" onclick={() => onOpen(item)}>나라장터에서 보기</button>
    <button class="button button--secondary" type="button" onclick={() => onAdd(item)}>리스트에 추가</button>
  </div>
</article>
