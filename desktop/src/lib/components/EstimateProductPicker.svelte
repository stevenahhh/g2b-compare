<script lang="ts">
  import { onMount } from "svelte";

  import { PREFERRED_COMPANY, relationIdentity } from "../catalog";
  import type { CatalogClient } from "../invoke";
  import type {
    CatalogPage,
    CatalogProduct,
    CatalogRelation,
    CatalogSort,
    RelationCategory,
  } from "../models";

  const categories: RelationCategory[] = ["selection", "additional", "construction"];
  const categoryLabels: Record<RelationCategory, string> = {
    selection: "선택품목",
    additional: "추가선택품목",
    construction: "공사",
  };
  const blankOptions = (): Record<RelationCategory, CatalogRelation[]> => ({
    selection: [],
    additional: [],
    construction: [],
  });

  let {
    client,
    disabled = false,
    onAdd,
  }: {
    client: CatalogClient;
    disabled?: boolean;
    onAdd: (item: CatalogProduct | CatalogRelation) => string;
  } = $props();

  let query = $state("");
  let sort = $state<CatalogSort>("price_asc");
  let products = $state<CatalogProduct[]>([]);
  let productPage = $state(1);
  let productPageCount = $state(1);
  let selected = $state<CatalogProduct | null>(null);
  let optionGroups = $state(blankOptions());
  let loading = $state(false);
  let optionsLoading = $state(false);
  let error = $state("");
  let status = $state("");
  let productTotal = $state(0);
  let searchVersion = 0;
  let optionVersion = 0;
  let disposed = false;
  let searchOpen = $state(false);
  let searchAnchor: HTMLElement;
  let searchInput: HTMLInputElement;
  let suppressSearchFocus = false;

  function message(caught: unknown): string {
    return caught instanceof Error ? caught.message : String(caught);
  }

  function uniqueItems<T>(items: T[], identity: (item: T) => string): T[] {
    const seen = new Set<string>();
    return items.filter((item) => {
      const key = identity(item);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  function pageCount(value: number): number {
    return Number.isFinite(value) ? Math.max(1, Math.floor(value)) : 1;
  }

  async function loadEveryPage<T>(
    loadPage: (page: number) => Promise<CatalogPage<T>>,
    current: () => boolean,
  ): Promise<CatalogPage<T>[] | null> {
    const pages: CatalogPage<T>[] = [];
    let requestedPage = 1;
    let lastPage = 1;
    while (requestedPage <= lastPage) {
      if (!current()) return null;
      const loaded = await loadPage(requestedPage);
      if (!current()) return null;
      pages.push(loaded);
      lastPage = pageCount(loaded.page_count);
      requestedPage += 1;
    }
    return pages;
  }

  async function search(requestedPage = 1) {
    const version = ++searchVersion;
    const requestedQuery = query.trim();
    const requestedSort = sort;
    optionVersion += 1;
    loading = true;
    optionsLoading = false;
    error = "";
    selected = null;
    optionGroups = blankOptions();
    try {
      const result = await client.searchProducts({
        company_name: PREFERRED_COMPANY,
        query: requestedQuery,
        sort: requestedSort,
        page: requestedPage,
      });
      if (disposed || version !== searchVersion) return;
      products = uniqueItems(result.items, (item) => item.product_id);
      productPage = result.page;
      productPageCount = pageCount(result.page_count);
      productTotal = result.total_count;
    } catch (caught) {
      if (!disposed && version === searchVersion) error = message(caught);
    } finally {
      if (!disposed && version === searchVersion) loading = false;
    }
  }

  async function selectProduct(product: CatalogProduct) {
    const version = ++optionVersion;
    const requestedSort = sort;
    selected = product;
    optionGroups = blankOptions();
    optionsLoading = true;
    error = "";
    try {
      const loadedGroups = blankOptions();
      for (const category of categories) {
        const pages = await loadEveryPage(
          (page) => client.searchRelations({
            parent_product_id: product.product_id,
            company_name: PREFERRED_COMPANY,
            category,
            query: product.product_id,
            sort: requestedSort,
            page,
          }),
          () => !disposed && version === optionVersion && selected?.product_id === product.product_id,
        );
        if (!pages) return;
        loadedGroups[category] = uniqueItems(
          pages.flatMap((page) => page.items).filter(
            (item) => item.parent_product_id === product.product_id,
          ),
          relationIdentity,
        );
      }
      if (disposed || version !== optionVersion || selected?.product_id !== product.product_id) return;
      const seen = new Set<string>();
      optionGroups = Object.fromEntries(categories.map((category) => [
        category,
        loadedGroups[category].filter((item) => {
          const identity = relationIdentity(item);
          if (seen.has(identity)) return false;
          seen.add(identity);
          return true;
        }),
      ])) as Record<RelationCategory, CatalogRelation[]>;
    } catch (caught) {
      if (!disposed && version === optionVersion) error = message(caught);
    } finally {
      if (!disposed && version === optionVersion) optionsLoading = false;
    }
  }

  function closeSelectedProduct() {
    optionVersion += 1;
    selected = null;
    optionGroups = blankOptions();
    optionsLoading = false;
  }

  function add(item: CatalogProduct | CatalogRelation) {
    status = "";
    error = onAdd(item);
    if (!error) status = `${item.name} 추가됨`;
  }

  function closeSearch(restoreFocus = true) {
    searchOpen = false;
    if (!restoreFocus) return;
    suppressSearchFocus = true;
    queueMicrotask(() => searchInput?.focus());
  }

  function focusSearch() {
    if (suppressSearchFocus) {
      suppressSearchFocus = false;
      return;
    }
    searchOpen = true;
  }

  function keydown(event: KeyboardEvent) {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    closeSearch();
  }

  function queryChanged(event: Event) {
    query = (event.currentTarget as HTMLInputElement).value;
    void search();
  }

  function sortChanged(event: Event) {
    sort = (event.currentTarget as HTMLSelectElement).value as CatalogSort;
    void search();
  }

  function outside(event: PointerEvent) {
    if (searchOpen && !searchAnchor.contains(event.target as Node)) closeSearch(false);
  }

  onMount(() => {
    globalThis.document.addEventListener("pointerdown", outside);
    void search();
    return () => {
      disposed = true;
      searchVersion += 1;
      optionVersion += 1;
      globalThis.document.removeEventListener("pointerdown", outside);
    };
  });
</script>

<section class="panel catalog-workspace document-catalog estimate-picker" aria-label="문서에 품목 추가">
  <div bind:this={searchAnchor} class="document-search-anchor estimate-picker__anchor">
    <form class="catalog-controls estimate-picker__controls" onsubmit={(event) => { event.preventDefault(); void search(); }}>
      <label for="document-product-search"><span>검색어</span><input bind:this={searchInput} id="document-product-search" type="search" value={query} autocomplete="off" placeholder="물품명, 규격 또는 업체명" aria-controls="document-search-results" onfocus={focusSearch} onclick={focusSearch} onkeydown={keydown} oninput={queryChanged} /></label>
      <label for="document-product-sort"><span>정렬</span><select id="document-product-sort" value={sort} onkeydown={keydown} onchange={sortChanged}><option value="price_asc">낮은 가격순</option><option value="price_desc">높은 가격순</option><option value="name_asc">품명순</option><option value="product_id_asc">식별번호순</option></select></label>
    </form>
    <div id="document-search-results" class:is-open={searchOpen} class="document-search-overlay estimate-picker__overlay" role="dialog" aria-modal="false" aria-hidden={!searchOpen} aria-label="물품 검색 결과" tabindex="-1" onkeydown={keydown}>
      <header class="document-search-overlay__header estimate-picker__overlay-header">
        <p class="catalog-summary estimate-picker__summary" aria-live="polite">{loading ? "검색 중" : `본품 검색 결과 ${productTotal.toLocaleString()}건`}</p>
        <button class="button button--secondary button--compact" type="button" onclick={() => closeSearch()}>검색 닫기</button>
      </header>
      {#if error}<p class="state-message state-message--error" role="status">{error}</p>{/if}
      {#if status}<p class="state-message state-message--success" role="status">{status}</p>{/if}
      <div class:selected-column={selected} class="document-search-columns estimate-picker__results" aria-busy={loading || optionsLoading}>
        <div class="document-result-scroll">
          <div class="catalog-grid">
            {#each products as product (product.product_id)}
              <article class:estimate-picker__product--selected={selected?.product_id === product.product_id} class="catalog-card estimate-picker__product">
                <button class="catalog-card__select document-result-card__body estimate-summary__open" type="button" aria-pressed={selected?.product_id === product.product_id} onclick={() => void selectProduct(product)}>
                  <div class="catalog-card__details"><strong>{product.name}</strong><span>{product.spec}</span><span class="catalog-card__price">{product.price_won.toLocaleString()}원 / {product.unit}</span></div>
                </button>
                <div class="catalog-card__actions"><button class="button button--secondary button--compact" type="button" {disabled} onclick={() => add(product)}>본품 추가</button></div>
              </article>
            {/each}
          </div>
          {#if !loading && products.length === 0}<p class="state-message">검색 결과 없음.</p>{/if}
          {#if productPageCount > 1}
            <nav class="estimate-picker__pagination" aria-label="검색 결과 페이지">
              <button class="button button--secondary button--compact" type="button" disabled={loading || productPage <= 1} onclick={() => void search(productPage - 1)}>이전 검색 결과</button>
              <span>{productPage.toLocaleString()} / {productPageCount.toLocaleString()} 페이지</span>
              <button class="button button--secondary button--compact" type="button" disabled={loading || productPage >= productPageCount} onclick={() => void search(productPage + 1)}>다음 검색 결과</button>
            </nav>
          {/if}
        </div>
        {#if selected}
          <aside class="document-option-panel" aria-label="연결된 하위 품목">
            <header class="document-option-panel__header"><div><span>선택한 본품</span><h2>{selected.name} · {selected.product_id}</h2></div><button class="button button--secondary button--compact" type="button" onclick={closeSelectedProduct}>닫기</button></header>
            <div class="document-option-groups">
              {#each categories as category}
                <section class="document-option-group estimate-picker__option-group">
                  <h3>{categoryLabels[category]} <span>{optionGroups[category].length.toLocaleString()}건</span></h3>
                  <div class="document-option-scroll">
                    {#if optionsLoading}<p class="option-loading">연결된 품목을 불러오는 중</p>
                    {:else if optionGroups[category].length === 0}<p class="option-empty">연결된 품목 없음.</p>
                    {:else}
                      {#each optionGroups[category] as option (relationIdentity(option))}
                        <article class="document-option-row estimate-picker__product estimate-picker__option"><div><strong>{option.name}</strong><span>{option.spec}</span><span class="option-row__price">{option.price_won.toLocaleString()}원 / {option.unit}</span></div><div class="catalog-card__actions"><button class="button button--secondary button--compact" type="button" {disabled} onclick={() => add(option)}>옵션 추가</button></div></article>
                      {/each}
                    {/if}
                  </div>
                </section>
              {/each}
            </div>
          </aside>
        {/if}
      </div>
    </div>
  </div>
</section>
