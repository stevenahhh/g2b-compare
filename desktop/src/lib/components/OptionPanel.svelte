<script lang="ts">
  import placeholderImage from "../../assets/product-placeholder.svg";
  import {
    OPTION_ROW_HEIGHT,
    OPTION_VIEWPORT_HEIGHT,
    relationIdentity,
    virtualWindow,
  } from "../catalog";
  import type {
    CatalogPage,
    CatalogProduct,
    CatalogRelation,
    RelationCategory,
  } from "../models";

  const categories: RelationCategory[] = ["selection", "additional", "construction"];
  const labels: Record<RelationCategory, string> = {
    selection: "선택품목",
    additional: "추가선택품목",
    construction: "공사",
  };

  let {
    selected,
    active,
    groups,
    loading,
    queries,
    scrollTop,
    onClose,
    onTab,
    onQuery,
    onScroll,
    onAdd,
    onOpen,
  }: {
    selected: CatalogProduct;
    active: RelationCategory;
    groups: Record<RelationCategory, CatalogPage<CatalogRelation>>;
    loading: Record<RelationCategory, boolean>;
    queries: Record<RelationCategory, string>;
    scrollTop: number;
    onClose: () => void;
    onTab: (category: RelationCategory) => void;
    onQuery: (category: RelationCategory, value: string) => void;
    onScroll: (category: RelationCategory, element: HTMLDivElement) => void;
    onAdd: (item: CatalogRelation) => void;
    onOpen: (item: CatalogRelation) => void;
  } = $props();

  const page = $derived(groups[active]);
  const visible = $derived(
    virtualWindow(page.items, scrollTop, OPTION_ROW_HEIGHT, OPTION_VIEWPORT_HEIGHT),
  );

  function imageFailed(event: Event) {
    const image = event.currentTarget as HTMLImageElement;
    image.onerror = null;
    image.src = placeholderImage;
  }

  function relationStatus(item: CatalogRelation): string {
    if (item.parent_product_id === selected.product_id) {
      return `연결됨 · 본품 ${selected.name} (${selected.product_id})`;
    }
    return `다른 본품 · ${item.parent_name || "본품 정보 없음"} (${item.parent_product_id})`;
  }
</script>

<aside class="option-panel" aria-labelledby="option-title">
  <header class="option-panel__header">
    <div>
      <span class="option-panel__eyebrow">선택한 본품</span>
      <h2 id="option-title">{selected.name} · {selected.product_id}</h2>
    </div>
    <button class="button--secondary button--compact" type="button" onclick={onClose}>닫기</button>
  </header>
  <div class="option-tabs" role="tablist" aria-label="연결된 품목 유형">
    {#each categories as category}
      <button
        class="option-tab"
        type="button"
        role="tab"
        id={`option-tab-${category}`}
        aria-selected={active === category}
        aria-controls="option-tabpanel"
        onclick={() => onTab(category)}
      >{labels[category]}<span>{groups[category].total_count.toLocaleString()}</span></button>
    {/each}
  </div>
  <div class="option-body" role="tabpanel" id="option-tabpanel" aria-labelledby={`option-tab-${active}`}>
    <div class="option-group__header">
      <label>
        <span class="visually-hidden">{labels[active]} 검색</span>
        <input
          type="search"
          value={queries[active]}
          placeholder={`${labels[active]} 검색`}
          oninput={(event) => onQuery(active, event.currentTarget.value)}
        />
      </label>
    </div>
    <div
      class="option-scroll"
      aria-busy={loading[active]}
      onscroll={(event) => onScroll(active, event.currentTarget)}
    >
      <div class="virtual-spacer" style:height={`${visible.top}px`}></div>
      {#each visible.items as item (relationIdentity(item))}
        <article class:option-row--connected={item.parent_product_id === selected.product_id} class="option-row">
          <img src={item.image_url || placeholderImage} alt={`${item.name} 상품 이미지`} onerror={imageFailed} />
          <div class="option-row__details">
            <strong>{item.name}</strong>
            <span>규격 · {item.spec || "수집된 규격 없음"}</span>
            <span class:relation-status--connected={item.parent_product_id === selected.product_id} class="relation-status">{relationStatus(item)}</span>
            <span class="option-row__price">{item.price_won.toLocaleString()}원 / {item.unit}</span>
          </div>
          <div class="catalog-card__actions">
            <button class="g2b-link" type="button" onclick={() => onOpen(item)}>나라장터에서 보기</button>
            <button class="button button--secondary" type="button" onclick={() => onAdd(item)}>리스트에 추가</button>
          </div>
        </article>
      {/each}
      <div class="virtual-spacer" style:height={`${visible.bottom}px`}></div>
      {#if loading[active] && page.items.length === 0}
        <div class="option-loading" role="status"><span class="loading-spinner" aria-hidden="true"></span><span>{labels[active]} 불러오는 중</span></div>
      {:else if !loading[active] && page.items.length === 0}
        <p class="state-message option-empty">{labels[active]} 없음.</p>
      {/if}
    </div>
  </div>
</aside>
