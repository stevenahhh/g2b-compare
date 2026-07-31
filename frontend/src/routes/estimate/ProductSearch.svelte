<script>
  import { onDestroy, onMount } from "svelte";
  import { requestJson } from "../../api.js";
  import { getCatalogCache, putCatalogCache } from "../../lib/db.js";
  import { loadDocumentOptions, loadDocumentProducts } from "./catalog.js";
  import ProductOptions from "./ProductOptions.svelte";
  import ProductResults from "./ProductResults.svelte";
  import { closeOnEscape } from "./keyboard.js";
  import "./ProductSearch.css";
  let {
    disabled = false,
    onAdd = () => "",
    onFailure = () => {},
  } = $props();
  let productSearch = $state("");
  let productSort = $state("price_asc");
  let productResults = $state([]);
  let productTotal = $state(0);
  let selectedProduct = $state(null);
  let selectedOptions = $state([]);
  let searching = $state(false);
  let optionsLoading = $state(false);
  let searchError = $state("");
  let searchOpen = $state(false);
  let searchAnchor;
  let searchInput;
  let suppressSearchFocus = false;
  let searchTimer;
  let searchVersion = 0;
  let optionsVersion = 0;
  const dependencies = { getCatalogCache, putCatalogCache, requestJson };
  async function searchProducts(query) {
    const version = ++searchVersion;
    let usedCache = false;
    searching = true;
    searchError = "";
    try {
      const loaded = await loadDocumentProducts(
        query,
        productSort,
        dependencies,
        (cached) => {
          if (version === searchVersion) {
            usedCache = true;
            productResults = cached.items;
            productTotal = cached.total_count;
          }
        },
      );
      if (version === searchVersion) {
        productResults = loaded.result.items;
        productTotal = loaded.result.total_count;
        if (!productResults.length) searchError = "일치하는 물품 없음.";
      }
    } catch (caught) {
      if (version === searchVersion) {
        onFailure(caught);
        if (!usedCache) {
          productResults = [];
          productTotal = 0;
        }
        searchError = "물품 검색 결과를 불러오지 못했음.";
      }
    } finally {
      if (version === searchVersion) searching = false;
    }
  }
  function queueSearch(event) {
    productSearch = event.currentTarget.value;
    searching = true;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(
      () => void searchProducts(productSearch.trim()),
      30,
    );
  }
  async function selectProduct(item) {
    const version = ++optionsVersion;
    let usedCache = false;
    selectedProduct = item;
    selectedOptions = [];
    optionsLoading = true;
    searchError = "";
    try {
      const loaded = await loadDocumentOptions(item, dependencies, (cached) => {
        if (version === optionsVersion) {
          usedCache = true;
          selectedOptions = cached.items;
        }
      });
      if (version === optionsVersion) selectedOptions = loaded.result.items;
    } catch (caught) {
      if (version === optionsVersion) {
        onFailure(caught);
        if (!usedCache) searchError = "연결된 품목을 불러오지 못했음.";
      }
    } finally {
      if (version === optionsVersion) optionsLoading = false;
    }
  }
  function closeSelectedProduct() {
    optionsVersion += 1;
    selectedProduct = null;
    selectedOptions = [];
    optionsLoading = false;
  }
  function add(item) {
    searchError = onAdd(item);
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
  function keydown(event) {
    if (closeOnEscape(event.key)) {
      event.preventDefault();
      event.stopPropagation();
      closeSearch();
    }
  }
  function outside(event) {
    if (searchOpen && searchAnchor && !searchAnchor.contains(event.target))
      closeSearch(false);
  }
  function sortChanged() {
    closeSelectedProduct();
    void searchProducts(productSearch.trim());
  }
  onMount(() => {
    globalThis.document.addEventListener("pointerdown", outside);
    void searchProducts("");
    return () =>
      globalThis.document.removeEventListener("pointerdown", outside);
  });
  onDestroy(() => clearTimeout(searchTimer));
</script>

<section
  class="panel catalog-workspace document-catalog"
  aria-label="물품 검색"
>
  <div class="document-search-anchor" bind:this={searchAnchor}>
    <div class="catalog-controls">
      <label for="document-product-search"
        ><span>검색어</span><input
          id="document-product-search"
          type="search"
          bind:this={searchInput}
          autocomplete="off"
          placeholder="물품명, 규격 또는 업체명"
          value={productSearch}
          aria-controls="document-search-results"
          onfocus={focusSearch}
          onclick={() => (searchOpen = true)}
          onkeydown={keydown}
          oninput={(event) => {
            closeSelectedProduct();
            queueSearch(event);
          }}
        /></label
      ><label for="document-product-sort"
        ><span>정렬</span><select
          id="document-product-sort"
          bind:value={productSort}
          onchange={sortChanged}
          onkeydown={keydown}
          ><option value="price_asc">낮은 가격순</option><option
            value="price_desc">높은 가격순</option
          ><option value="name_asc">품명순</option><option
            value="product_id_asc">식별번호순</option
          ></select
        ></label
      >
    </div>
    <div
      id="document-search-results"
      class="document-search-overlay"
      class:is-open={searchOpen}
      role="dialog"
      aria-modal="false"
      tabindex="-1"
      aria-label="물품 검색 결과"
      onkeydown={keydown}
    >
      <div class="document-search-overlay__header">
        <p class="catalog-summary" aria-live="polite">
          {#if searching}<span class="loading-label"
              ><span class="loading-spinner" aria-hidden="true"></span>검색 중</span
            >{:else}본품 검색 결과 {productTotal.toLocaleString()}건{/if}
        </p>
        <button
          class="button--secondary"
          type="button"
          onclick={() => closeSearch()}>닫기</button
        >
      </div>
      {#if searchError}<p
          class="state-message state-message--error"
          role="status"
        >
          {searchError}
        </p>{/if}
      <div
        class:selected-column={selectedProduct}
        class="document-search-columns"
      >
        <ProductResults
          items={productResults}
          {selectedProduct}
          {searching}
          {disabled}
          onSelect={selectProduct}
          onAdd={add}
        />{#if selectedProduct}<ProductOptions
            {selectedProduct}
            items={selectedOptions}
            loading={optionsLoading}
            {disabled}
            onClose={closeSelectedProduct}
            onAdd={add}
          />{/if}
      </div>
    </div>
  </div>
</section>

