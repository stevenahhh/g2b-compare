<script lang="ts">
  import { onDestroy, onMount } from "svelte";

  import OptionPanel from "../lib/components/OptionPanel.svelte";
  import ProductCard from "../lib/components/ProductCard.svelte";
  import {
    OPTION_ROW_HEIGHT,
    PREFERRED_COMPANY,
    PRODUCT_ROW_HEIGHT,
    PRODUCT_VIEWPORT_HEIGHT,
    defaultCatalogView,
    emptyPage,
    isCatalogSort,
    mergePage,
    relationIdentity,
    virtualWindow,
  } from "../lib/catalog";
  import { catalogClient, type CatalogClient } from "../lib/invoke";
  import type {
    CatalogPage,
    CatalogProduct,
    CatalogRelation,
    CatalogViewState,
    RelationCategory,
  } from "../lib/models";
  import { createTransientFeedbackDeadline } from "../lib/transientFeedback";

  const categories: RelationCategory[] = ["selection", "additional", "construction"];
  const blankQueries = (): Record<RelationCategory, string> => ({
    selection: "",
    additional: "",
    construction: "",
  });
  const blankPages = (): Record<RelationCategory, number> => ({
    selection: 1,
    additional: 1,
    construction: 1,
  });
  const blankScroll = (): Record<RelationCategory, number> => ({
    selection: 0,
    additional: 0,
    construction: 0,
  });
  const blankGroups = (): Record<RelationCategory, CatalogPage<CatalogRelation>> => ({
    selection: emptyPage<CatalogRelation>(),
    additional: emptyPage<CatalogRelation>(),
    construction: emptyPage<CatalogRelation>(),
  });
  const blankLoading = (): Record<RelationCategory, boolean> => ({
    selection: false,
    additional: false,
    construction: false,
  });

  let { client = catalogClient }: { client?: CatalogClient } = $props();
  let query = $state("");
  let sort = $state<CatalogViewState["sort"]>("price_asc");
  let page = $state(1);
  let products = $state<CatalogPage<CatalogProduct>>(emptyPage<CatalogProduct>());
  let selected = $state<CatalogProduct | null>(null);
  let groups = $state(blankGroups());
  let relationQueries = $state(blankQueries());
  let relationPages = $state(blankPages());
  let relationScroll = $state(blankScroll());
  let relationLoading = $state(blankLoading());
  let activeCategory = $state<RelationCategory>("selection");
  let productScrollTop = $state(0);
  let loading = $state(true);
  let error = $state("");
  let actionStatus = $state("");
  let actionFailed = $state(false);
  let restored = false;
  let productRequestVersion = 0;
  const relationRequestVersion: Record<RelationCategory, number> = {
    selection: 0,
    additional: 0,
    construction: 0,
  };
  const relationTimers: Partial<Record<RelationCategory, ReturnType<typeof setTimeout>>> = {};
  const actionFeedbackDeadline = createTransientFeedbackDeadline(() => {
    actionStatus = "";
    actionFailed = false;
  });

  const visibleProducts = $derived(
    virtualWindow(
      products.items,
      productScrollTop,
      PRODUCT_ROW_HEIGHT,
      PRODUCT_VIEWPORT_HEIGHT,
    ),
  );

  function errorMessage(caught: unknown): string {
    return caught instanceof Error ? caught.message : String(caught);
  }

  function currentView(): CatalogViewState {
    return {
      query,
      sort,
      page,
      selected_product_id: selected?.product_id ?? null,
      active_category: activeCategory,
      product_scroll_top: productScrollTop,
      relation_scroll_top: { ...relationScroll },
      relation_query: { ...relationQueries },
      relation_page: { ...relationPages },
    };
  }

  function saveView() {
    if (!restored) return;
    void client.saveView(currentView()).catch(() => undefined);
  }

  async function loadProducts(requestedPage: number) {
    const version = ++productRequestVersion;
    loading = true;
    error = "";
    try {
      const result = await client.searchProducts({
        company_name: "",
        query: query.trim(),
        sort,
        page: requestedPage,
      });
      if (version !== productRequestVersion) return;
      products = mergePage(products, result, requestedPage, (item) => item.product_id);
      page = requestedPage;
    } catch (caught) {
      if (version === productRequestVersion) {
        error = requestedPage === 1
          ? "저장된 검색 결과가 없어 표시할 수 없습니다."
          : errorMessage(caught);
      }
    } finally {
      if (version === productRequestVersion) loading = false;
    }
  }

  async function loadRelation(category: RelationCategory, requestedPage: number) {
    if (!selected) return;
    const selectedId = selected.product_id;
    const version = ++relationRequestVersion[category];
    relationLoading = { ...relationLoading, [category]: true };
    try {
      const result = await client.searchRelations({
        parent_product_id: selectedId,
        company_name: PREFERRED_COMPANY,
        category,
        query: relationQueries[category].trim(),
        sort,
        page: requestedPage,
      });
      if (
        version !== relationRequestVersion[category] ||
        selected?.product_id !== selectedId
      ) return;
      groups = {
        ...groups,
        [category]: mergePage(
          groups[category],
          {
            ...result,
            items: result.items.filter((item) => item.parent_product_id === selectedId),
          },
          requestedPage,
          relationIdentity,
        ),
      };
      relationPages = { ...relationPages, [category]: requestedPage };
    } catch (caught) {
      if (version === relationRequestVersion[category]) error = errorMessage(caught);
    } finally {
      if (version === relationRequestVersion[category]) {
        relationLoading = { ...relationLoading, [category]: false };
      }
    }
  }

  async function selectProduct(product: CatalogProduct, state?: CatalogViewState) {
    selected = product;
    groups = blankGroups();
    relationQueries = state?.relation_query ? { ...state.relation_query } : blankQueries();
    relationPages = blankPages();
    relationScroll = state?.relation_scroll_top
      ? { ...state.relation_scroll_top }
      : blankScroll();
    activeCategory = state?.active_category ?? "selection";
    saveView();
    await Promise.all(
      categories.map(async (category) => {
        const lastPage = Math.max(1, state?.relation_page?.[category] ?? 1);
        for (let requestedPage = 1; requestedPage <= lastPage; requestedPage += 1) {
          await loadRelation(category, requestedPage);
        }
      }),
    );
  }

  function closeOptions() {
    for (const category of categories) relationRequestVersion[category] += 1;
    selected = null;
    groups = blankGroups();
    relationQueries = blankQueries();
    relationPages = blankPages();
    relationScroll = blankScroll();
    activeCategory = "selection";
    saveView();
  }

  function resetProducts() {
    productRequestVersion += 1;
    page = 1;
    products = emptyPage<CatalogProduct>();
    productScrollTop = 0;
    closeOptions();
    void loadProducts(1);
    saveView();
  }

  function searchChanged(value: string) {
    query = value;
    resetProducts();
  }

  function sortChanged(value: string) {
    if (!isCatalogSort(value)) return;
    sort = value;
    resetProducts();
  }

  function productScrolled(element: HTMLDivElement) {
    productScrollTop = element.scrollTop;
    saveView();
    if (
      !loading &&
      page < products.page_count &&
      element.scrollTop + element.clientHeight >= element.scrollHeight - PRODUCT_ROW_HEIGHT
    ) {
      void loadProducts(page + 1);
    }
  }

  function tabChanged(category: RelationCategory) {
    activeCategory = category;
    saveView();
  }

  function relationQueryChanged(category: RelationCategory, value: string) {
    relationQueries = { ...relationQueries, [category]: value };
    groups = { ...groups, [category]: emptyPage<CatalogRelation>() };
    relationPages = { ...relationPages, [category]: 1 };
    relationScroll = { ...relationScroll, [category]: 0 };
    const timer = relationTimers[category];
    if (timer) clearTimeout(timer);
    relationTimers[category] = setTimeout(() => void loadRelation(category, 1), 80);
    saveView();
  }

  function relationScrolled(category: RelationCategory, element: HTMLDivElement) {
    relationScroll = { ...relationScroll, [category]: element.scrollTop };
    saveView();
    if (
      !relationLoading[category] &&
      relationPages[category] < groups[category].page_count &&
      element.scrollTop + element.clientHeight >= element.scrollHeight - OPTION_ROW_HEIGHT
    ) {
      void loadRelation(category, relationPages[category] + 1);
    }
  }

  async function addProduct(item: CatalogProduct | CatalogRelation, relation?: CatalogRelation) {
    actionFeedbackDeadline.cancel();
    actionStatus = "";
    actionFailed = false;
    error = "";
    if (relation && relation.parent_product_id !== selected?.product_id) {
      actionFailed = true;
      actionStatus = "선택한 본품에 연결된 품목만 추가할 수 있습니다.";
      actionFeedbackDeadline.reset();
      return;
    }
    try {
      const result = await client.addItem({
        product_id: item.product_id,
        line_kind: relation ? "option" : "main",
        parent_product_id: relation ? relation.parent_product_id : null,
        relation_id: relation ? relationIdentity(relation) : null,
      });
      actionStatus = `리스트에 추가함 · ${result.line_count}개 품목`;
    } catch (caught) {
      actionFailed = true;
      actionStatus = errorMessage(caught);
    } finally {
      actionFeedbackDeadline.reset();
    }
  }

  async function openProduct(item: CatalogProduct | CatalogRelation) {
    error = "";
    try {
      await client.openProduct(item.g2b_url || item.detail_url);
    } catch (caught) {
      error = errorMessage(caught);
    }
  }

  async function restore() {
    let state = defaultCatalogView();
    try {
      state = (await client.loadView()) ?? state;
    } catch {
      // A missing view is equivalent to first launch; catalog loading still proceeds.
    }
    query = typeof state.query === "string" ? state.query : "";
    sort = isCatalogSort(state.sort) ? state.sort : "price_asc";
    const lastPage = Math.max(1, state.page || 1);
    for (let requestedPage = 1; requestedPage <= lastPage; requestedPage += 1) {
      await loadProducts(requestedPage);
    }
    const restoredProduct = products.items.find(
      (item) => item.product_id === state.selected_product_id,
    );
    if (restoredProduct) await selectProduct(restoredProduct, state);
    productScrollTop = Math.max(0, state.product_scroll_top || 0);
    restored = true;
    saveView();
  }

  onMount(() => {
    void restore();
  });

  onDestroy(() => {
    actionFeedbackDeadline.cancel();
    for (const timer of Object.values(relationTimers)) {
      if (timer) clearTimeout(timer);
    }
  });
</script>

<header class="page-header"><h2>물품 검색</h2></header>
<section class="panel catalog-workspace">
  <div class="catalog-controls">
    <label for="catalog-search">
      <span>검색어</span>
      <input
        id="catalog-search"
        type="search"
        value={query}
        autocomplete="off"
        placeholder="물품명, 규격 또는 업체명"
        oninput={(event) => searchChanged(event.currentTarget.value)}
      />
    </label>
    <label for="catalog-sort">
      <span>정렬</span>
      <select id="catalog-sort" value={sort} onchange={(event) => sortChanged(event.currentTarget.value)}>
        <option value="price_asc">낮은 가격순</option>
        <option value="price_desc">높은 가격순</option>
        <option value="name_asc">품명순</option>
        <option value="product_id_asc">식별번호순</option>
      </select>
    </label>
  </div>
  {#if error}<p class="state-message state-message--error" role="status">{error}</p>{/if}
  {#if actionStatus}<p class:state-message--error={actionFailed} class:state-message--success={!actionFailed} class="state-message" role="status">{actionStatus}</p>{/if}
  <p class="catalog-summary" aria-live="polite">
    {#if loading}<span class="loading-label"><span class="loading-spinner" aria-hidden="true"></span>검색 중</span>
    {:else}본품 {products.total_count.toLocaleString()}건{/if}
  </p>
  <div class:catalog-columns--selected={selected} class="catalog-columns">
    <div
      class="catalog-scroll"
      aria-busy={loading}
      onscroll={(event) => productScrolled(event.currentTarget)}
    >
      <div class="catalog-grid">
        {#if loading && products.items.length === 0}
          {#each [1, 2, 3] as placeholder}
            <article class="loading-card" aria-hidden="true">
              <span class="loading-placeholder loading-placeholder--image"></span>
              <div class="loading-card__body">
                <span class="loading-placeholder loading-placeholder--title"></span>
                <span class="loading-placeholder loading-placeholder--text"></span>
                <span class="loading-placeholder loading-placeholder--short"></span>
              </div>
            </article>
          {/each}
        {/if}
        <div class="virtual-spacer" style:height={`${visibleProducts.top}px`}></div>
        {#each visibleProducts.items as item (item.product_id)}
          <ProductCard
            {item}
            selected={selected?.product_id === item.product_id}
            onSelect={(product) => void selectProduct(product)}
            onAdd={(product) => void addProduct(product)}
            onOpen={(product) => void openProduct(product)}
          />
        {/each}
        <div class="virtual-spacer" style:height={`${visibleProducts.bottom}px`}></div>
      </div>
      {#if !loading && products.items.length === 0}
        <div class="empty-state"><h3>검색 결과 없음</h3><p>다른 검색어를 입력해 보세요.</p></div>
      {/if}
    </div>
    {#if selected}
      <OptionPanel
        {selected}
        active={activeCategory}
        {groups}
        loading={relationLoading}
        queries={relationQueries}
        scrollTop={relationScroll[activeCategory]}
        onClose={closeOptions}
        onTab={tabChanged}
        onQuery={relationQueryChanged}
        onScroll={relationScrolled}
        onAdd={(relation) => void addProduct(relation, relation)}
        onOpen={(relation) => void openProduct(relation)}
      />
    {/if}
  </div>
</section>
