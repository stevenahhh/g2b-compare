<script>
  import { onMount } from "svelte";
  import { requestJson } from "../api.js";
  import { getAllEstimates, getAppState, getCatalogCache, getEstimate, putAppState, putCatalogCache, putEstimate } from "../lib/db.js";
  import { syncPendingEstimates } from "../lib/sync.js";

  let { search = "", onSearch = () => {}, onFailure = () => {}, onSynced = () => {} } = $props();
  const PAGE_SIZE = 30;
  const CATALOG_ROW_HEIGHT = 216;
  const OPTION_ROW_HEIGHT = 224;
  const OVERSCAN = 4;
  const OPTION_KINDS = ["component", "additional"];
  const emptyPage = () => ({ items: [], page: 1, page_count: 1, total_count: 0 });
  let sort = $state("price_asc");
  let page = $state(1);
  let result = $state(emptyPage());
  let selected = $state(null);
  let options = $state({ component: emptyPage(), additional: emptyPage() });
  let optionPages = $state({ component: 1, additional: 1 });
  let optionLoading = $state({ component: false, additional: false });
  let loading = $state(false);
  let error = $state("");
  let listElement;
  let componentElement = $state();
  let additionalElement = $state();
  let restored = $state(false);
  let requestVersion = 0;
  const optionRequestVersions = { component: 0, additional: 0 };
  let catalogScrollTop = $state(0);
  let optionScrollTop = $state({ component: 0, additional: 0 });
  let loadedSearch = null;
  let loadedSort = null;
  const catalogKey = (requestedPage) => `catalog:${search}:${sort}:${requestedPage}`;
  const optionKey = (productId, kind, requestedPage) => `options:v2:${productId}:${kind}:${requestedPage}`;
  const catalogWindow = $derived(windowFor(result.items, catalogScrollTop, CATALOG_ROW_HEIGHT, 560));
  const componentWindow = $derived(windowFor(options.component.items, optionScrollTop.component, OPTION_ROW_HEIGHT, 280));
  const additionalWindow = $derived(windowFor(options.additional.items, optionScrollTop.additional, OPTION_ROW_HEIGHT, 280));

  function id() { return [...crypto.getRandomValues(new Uint8Array(16))].map((value) => value.toString(16).padStart(2, "0")).join(""); }
  function titleFor(sequence) {
    const now = new Date();
    const stamp = [now.getFullYear(), String(now.getMonth() + 1).padStart(2, "0"), String(now.getDate()).padStart(2, "0")].join("") + "-" + [String(now.getHours()).padStart(2, "0"), String(now.getMinutes()).padStart(2, "0"), String(now.getSeconds()).padStart(2, "0")].join("");
    return `${sequence}-${stamp}`;
  }
  function windowFor(items, scrollTop, rowHeight, viewportHeight) {
    const start = Math.max(0, Math.floor(scrollTop / rowHeight) - OVERSCAN);
    const end = Math.min(items.length, start + Math.ceil(viewportHeight / rowHeight) + OVERSCAN * 2);
    return { items: items.slice(start, end), top: start * rowHeight, bottom: (items.length - end) * rowHeight };
  }
  function compactCompanyName(value) {
    return String(value ?? "").replace(/^(?:주식회사|\(주\)|㈜)\s*/u, "").trim();
  }
  function productTitle(item) {
    const specParts = String(item.spec ?? "").split(",").map((part) => part.trim()).filter(Boolean);
    const purpose = item.attributes?.find((attribute) => attribute.name === "용도")?.value ?? (specParts.length > 3 ? specParts.at(-1) : "");
    return [...new Set([item.name, specParts[1] || compactCompanyName(item.company_name), specParts[2], purpose].filter(Boolean))].join(", ");
  }
  async function saveView() {
    if (!restored) return;
    await putAppState("catalogView", {
      sort,
      page,
      optionPages: { ...optionPages },
      selectedProductId: selected?.product_id ?? null,
      scrollTop: catalogScrollTop,
      optionScrollTop: { ...optionScrollTop },
    });
  }
  function mergeCatalogPage(previous, incoming, requestedPage) {
    const before = requestedPage === 1 ? [] : previous.items;
    const ids = new Set(before.map((item) => item.product_id));
    return { ...incoming, items: [...before, ...incoming.items.filter((item) => !ids.has(item.product_id))] };
  }
  function mergeOptionPage(previous, incoming, requestedPage) {
    const before = requestedPage === 1 ? [] : previous.items;
    const ids = new Set(before.map((item) => item.relation_id));
    return { ...incoming, items: [...before, ...incoming.items.filter((item) => !ids.has(item.relation_id))] };
  }
  async function loadCatalog(requestedPage = 1) {
    const version = ++requestVersion;
    loading = true;
    error = "";
    const key = catalogKey(requestedPage);
    const cached = await getCatalogCache(key).catch(() => null);
    if (cached && version === requestVersion) result = mergeCatalogPage(result, cached, requestedPage);
    try {
      const online = await requestJson(`/api/catalog/products?q=${encodeURIComponent(search)}&sort=${sort}&page=${requestedPage}&page_size=${PAGE_SIZE}`);
      if (version === requestVersion) result = mergeCatalogPage(result, online, requestedPage);
      try { await putCatalogCache(key, online); } catch {}
    } catch (caught) {
      onFailure(caught);
      if (!cached && version === requestVersion) error = "저장된 검색 결과가 없어 현재 검색을 표시할 수 없음.";
    } finally {
      if (version === requestVersion) loading = false;
    }
  }
  async function loadOptions(kind, requestedPage = 1) {
    if (!selected) return;
    const version = ++optionRequestVersions[kind];
    optionLoading = { ...optionLoading, [kind]: true };
    const productId = selected.product_id;
    const key = optionKey(productId, kind, requestedPage);
    const cached = await getCatalogCache(key).catch(() => null);
    if (cached && version === optionRequestVersions[kind] && selected?.product_id === productId) {
      options = { ...options, [kind]: mergeOptionPage(options[kind], cached, requestedPage) };
    }
    try {
      const online = await requestJson(`/api/catalog/products/${encodeURIComponent(productId)}/options?relation_kind=${kind}&page=${requestedPage}&page_size=${PAGE_SIZE}`);
      if (version === optionRequestVersions[kind] && selected?.product_id === productId) {
        options = { ...options, [kind]: mergeOptionPage(options[kind], online, requestedPage) };
      }
      try { await putCatalogCache(key, online); } catch {}
    } catch (caught) {
      if (version === optionRequestVersions[kind]) {
        onFailure(caught);
        if (!cached) error = caught.message;
      }
    } finally {
      if (version === optionRequestVersions[kind]) optionLoading = { ...optionLoading, [kind]: false };
    }
  }
  async function select(product, restoredPages = { component: 1, additional: 1 }) {
    selected = product;
    options = { component: emptyPage(), additional: emptyPage() };
    optionPages = { component: 1, additional: 1 };
    optionScrollTop = { component: 0, additional: 0 };
    await saveView();
    await Promise.all(OPTION_KINDS.map(async (kind) => {
      const lastPage = Math.max(1, restoredPages[kind] ?? 1);
      for (let requestedPage = 1; requestedPage <= lastPage; requestedPage += 1) {
        optionPages = { ...optionPages, [kind]: requestedPage };
        await loadOptions(kind, requestedPage);
      }
    }));
  }
  function closeOptions() {
    optionRequestVersions.component += 1;
    optionRequestVersions.additional += 1;
    selected = null;
    options = { component: emptyPage(), additional: emptyPage() };
    optionPages = { component: 1, additional: 1 };
    optionScrollTop = { component: 0, additional: 0 };
    void saveView();
  }
  async function add(item, kind, parent = null) {
    const storedActiveId = await getAppState("activeEstimateId");
    const activeRecord = storedActiveId ? await getEstimate(storedActiveId) : null;
    const activeId = !storedActiveId || activeRecord?.deleted ? id() : storedActiveId;
    const existing = activeId === storedActiveId ? activeRecord : null;
    const document = existing?.document ?? { id: activeId, title: titleFor((await getAllVisibleCount()) + 1), lines: [] };
    if (document.lines.length >= 9) { error = "문서에는 품목을 최대 9개까지 추가할 수 있음."; return; }
    document.lines = [...document.lines, { id: id(), line_kind: kind, product_id: item.product_id, parent_product_id: parent?.product_id ?? null, relation_id: item.relation_id ?? null, offer_operation: null, offer_key: null, item_name_snapshot: item.name, spec_snapshot: item.spec, company_snapshot: item.company_name, unit_snapshot: item.unit, unit_price_won_snapshot: item.price_won, quantity: "1" }];
    await putEstimate(document);
    await putAppState("activeEstimateId", activeId);
    void syncPendingEstimates(globalThis.fetch, onSynced);
  }
  async function getAllVisibleCount() { return (await getAllEstimates()).filter((record) => !record.deleted && record.document.lines.length).length; }
  function changeSearch(event) { onSearch(event.currentTarget.value); page = 1; result = emptyPage(); closeOptions(); }
  function changeSort() { page = 1; result = emptyPage(); closeOptions(); }
  function scrollCatalog() {
    catalogScrollTop = listElement.scrollTop;
    void saveView();
    if (!loading && page < result.page_count && listElement.scrollTop + listElement.clientHeight >= listElement.scrollHeight - 160) {
      page += 1;
      void loadCatalog(page);
    }
  }
  function scrollOptions(kind) {
    const element = kind === "component" ? componentElement : additionalElement;
    if (!element) return;
    optionScrollTop = { ...optionScrollTop, [kind]: element.scrollTop };
    void saveView();
    if (!optionLoading[kind] && optionPages[kind] < options[kind].page_count && element.scrollTop + element.clientHeight >= element.scrollHeight - 120) {
      const nextPage = optionPages[kind] + 1;
      optionPages = { ...optionPages, [kind]: nextPage };
      void loadOptions(kind, nextPage);
    }
  }

  onMount(() => {
    void getAppState("catalogView").then(async (state) => {
      let initialSearch = search;
      let initialSort = sort;
      if (state) {
        sort = state.sort ?? sort;
        initialSearch = search;
        initialSort = sort;
        const restoredPage = Math.max(1, state.page ?? 1);
        for (let requestedPage = 1; requestedPage <= restoredPage; requestedPage += 1) {
          page = requestedPage;
          await loadCatalog(requestedPage);
        }
        if (state.selectedProductId) {
          const item = result.items.find((candidate) => candidate.product_id === state.selectedProductId);
          if (item) await select(item, state.optionPages ?? { component: state.optionPage ?? 1, additional: state.optionPage ?? 1 });
        }
        catalogScrollTop = state.scrollTop ?? 0;
        optionScrollTop = typeof state.optionScrollTop === "object" ? state.optionScrollTop : { component: state.optionScrollTop ?? 0, additional: state.optionScrollTop ?? 0 };
        requestAnimationFrame(() => {
          if (listElement) listElement.scrollTop = catalogScrollTop;
          if (componentElement) componentElement.scrollTop = optionScrollTop.component;
          if (additionalElement) additionalElement.scrollTop = optionScrollTop.additional;
        });
      } else {
        await loadCatalog(1);
      }
      loadedSearch = initialSearch;
      loadedSort = initialSort;
      restored = true;
    }).catch(() => {
      loadedSearch = search;
      loadedSort = sort;
      restored = true;
      void loadCatalog(1);
    });
  });
  $effect(() => {
    if (!restored || (search === loadedSearch && sort === loadedSort)) return;
    loadedSearch = search;
    loadedSort = sort;
    page = 1;
    catalogScrollTop = 0;
    result = emptyPage();
    closeOptions();
    void loadCatalog(1);
    void saveView();
  });
</script>

<header class="page-header"><h1>물품 검색</h1></header>
<section class="panel catalog-workspace">
  <div class="catalog-controls">
    <label for="catalog-search"><span>검색어</span><input id="catalog-search" type="search" value={search} placeholder="물품명, 규격 또는 업체명" oninput={changeSearch} /></label>
    <label for="catalog-sort"><span>정렬</span><select id="catalog-sort" bind:value={sort} onchange={changeSort}><option value="price_asc">낮은 가격순</option><option value="price_desc">높은 가격순</option><option value="name_asc">품명순</option><option value="product_id_asc">식별번호순</option></select></label>
  </div>
  {#if error}<p class="state-message state-message--error">{error}</p>{/if}
  <p class="catalog-summary" aria-live="polite">
    {#if loading}<span class="loading-label"><span class="loading-spinner" aria-hidden="true"></span>검색 중</span>
    {:else}검색 결과 {result.total_count.toLocaleString()}건{/if}
  </p>
  <div class:selected-column={selected} class="catalog-columns">
    <div class="catalog-scroll" bind:this={listElement} onscroll={scrollCatalog} aria-busy={loading}>
      <div class="catalog-grid">
        {#if loading && result.items.length === 0}
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
        <div class="virtual-spacer" style:height={`${catalogWindow.top}px`}></div>
        {#each catalogWindow.items as item (item.product_id)}
          <article class="catalog-card">
            <button class="catalog-card__select" type="button" aria-pressed={selected?.product_id === item.product_id} onclick={() => select(item)}>
              <img src={item.image_url || "/static/product-placeholder.svg"} alt={`${item.name} 상품 이미지`} onerror={(event) => { event.currentTarget.onerror = null; event.currentTarget.src = "/static/product-placeholder.svg"; }} />
              <div class="catalog-card__details">
                <strong>{productTitle(item)}</strong>
                <span class="catalog-card__price">{item.price_won?.toLocaleString()}원 / {item.unit}</span>
                <span>{item.contract_method} · {item.delivery_condition} · 납기 {item.delivery_days}일 · {item.contract_end_date}</span>
                <dl class="attribute-list">{#each item.attributes ?? [] as attribute}<div><dt>{attribute.name}</dt><dd>{attribute.value}{attribute.unit}</dd></div>{/each}</dl>
              </div>
            </button>
            <div class="catalog-card__actions"><a class="g2b-link" href={item.g2b_url}>나라장터</a><button class="button button--secondary" type="button" onclick={() => add(item, "main")}>내역 추가</button></div>
          </article>
        {/each}
        <div class="virtual-spacer" style:height={`${catalogWindow.bottom}px`}></div>
      </div>
      {#if !loading && result.items.length === 0}<div class="empty-state"><h2>검색 결과 없음</h2><p>다른 검색어를 입력해 보세요.</p></div>{/if}
    </div>
    {#if selected}
      <aside class="option-panel" aria-labelledby="option-title">
        <header class="option-panel__header"><h2 id="option-title">{selected.name}</h2><button class="button--secondary" type="button" onclick={closeOptions}>닫기</button></header>
        <div class="option-groups">
          <section class="option-group" aria-labelledby="component-title">
            <h3 id="component-title">선택품목 <span>{options.component.total_count.toLocaleString()}건</span></h3>
            <div class="option-scroll" bind:this={componentElement} onscroll={() => scrollOptions("component")} aria-busy={optionLoading.component}>
              <div class="virtual-spacer" style:height={`${componentWindow.top}px`}></div>
              {#each componentWindow.items as item (`${item.relation_id}:${item.product_id}`)}
                <article class="option-row">
                  <img src={item.image_url || "/static/product-placeholder.svg"} alt={`${item.name} 상품 이미지`} onerror={(event) => { event.currentTarget.onerror = null; event.currentTarget.src = "/static/product-placeholder.svg"; }} />
                  <div class="option-row__details"><strong>{item.name}</strong><span>{item.company_name}</span><span>{item.spec.replace(/\s+:\s+(?=[\d,])/g, "\u00a0:\u00a0")}</span><span class="option-row__price">{item.price_won?.toLocaleString()}원 / {item.unit}</span><dl class="attribute-list">{#each item.attributes ?? [] as attribute}<div><dt>{attribute.name}</dt><dd>{attribute.value}{attribute.unit}</dd></div>{/each}</dl></div>
                  <div class="catalog-card__actions"><a class="g2b-link" href={item.g2b_url}>나라장터</a><button class="button button--secondary" type="button" onclick={() => add(item, "option", selected)}>내역 추가</button></div>
                </article>
              {/each}
              <div class="virtual-spacer" style:height={`${componentWindow.bottom}px`}></div>
              {#if optionLoading.component && options.component.items.length === 0}
                <div class="option-loading" role="status"><span class="loading-spinner" aria-hidden="true"></span><span>선택품목 불러오는 중</span></div>
              {/if}
              {#if !optionLoading.component && options.component.items.length === 0}<p class="state-message option-empty">선택품목 없음.</p>{/if}
            </div>
          </section>
          <section class="option-group" aria-labelledby="additional-title">
            <h3 id="additional-title">추가선택품목 <span>{options.additional.total_count.toLocaleString()}건</span></h3>
            <div class="option-scroll" bind:this={additionalElement} onscroll={() => scrollOptions("additional")} aria-busy={optionLoading.additional}>
              <div class="virtual-spacer" style:height={`${additionalWindow.top}px`}></div>
              {#each additionalWindow.items as item (`${item.relation_id}:${item.product_id}`)}
                <article class="option-row">
                  <img src={item.image_url || "/static/product-placeholder.svg"} alt={`${item.name} 상품 이미지`} onerror={(event) => { event.currentTarget.onerror = null; event.currentTarget.src = "/static/product-placeholder.svg"; }} />
                  <div class="option-row__details"><strong>{item.name}</strong><span>{item.company_name}</span><span>{item.spec.replace(/\s+:\s+(?=[\d,])/g, "\u00a0:\u00a0")}</span><span class="option-row__price">{item.price_won?.toLocaleString()}원 / {item.unit}</span><dl class="attribute-list">{#each item.attributes ?? [] as attribute}<div><dt>{attribute.name}</dt><dd>{attribute.value}{attribute.unit}</dd></div>{/each}</dl></div>
                  <div class="catalog-card__actions"><a class="g2b-link" href={item.g2b_url}>나라장터</a><button class="button button--secondary" type="button" onclick={() => add(item, "option", selected)}>내역 추가</button></div>
                </article>
              {/each}
              <div class="virtual-spacer" style:height={`${additionalWindow.bottom}px`}></div>
              {#if optionLoading.additional && options.additional.items.length === 0}
                <div class="option-loading" role="status"><span class="loading-spinner" aria-hidden="true"></span><span>추가선택품목 불러오는 중</span></div>
              {/if}
              {#if !optionLoading.additional && options.additional.items.length === 0}<p class="state-message option-empty">추가선택품목 없음.</p>{/if}
            </div>
          </section>
        </div>
      </aside>
    {/if}
  </div>
</section>

<style>
  .catalog-card__select { align-self: stretch; align-items: center; }
  .catalog-columns.selected-column .catalog-card { grid-template-columns: minmax(0, 1fr) 112px; }
  .option-panel { display: grid; block-size: clamp(560px, calc(100dvh - 264px), 760px); grid-template-rows: auto minmax(0, 1fr); }
  .option-panel__header { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: var(--space-3); padding: var(--space-3) var(--space-4); border-block-end: 1px solid var(--line); background: var(--surface-subtle); }
  .option-panel__header h2 { min-width: 0; margin: 0; font-size: 15px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .option-panel__header button { min-height: 36px; padding-inline: var(--space-3); }
  .option-groups { display: grid; min-height: 0; grid-template-rows: repeat(2, minmax(0, 1fr)); }
  .option-group { display: grid; min-height: 0; grid-template-rows: auto minmax(0, 1fr); }
  .option-group + .option-group { border-block-start: 1px solid var(--line); }
  .option-group h3 { margin: 0; padding: var(--space-2) var(--space-4); border-block-end: 1px solid var(--line); font-size: 13px; }
  .option-group h3 span { margin-inline-start: var(--space-1); color: var(--muted); font-weight: 400; }
  .option-panel .option-scroll { block-size: auto; min-height: 0; padding-inline-end: 0; }
  .option-row { display: grid; grid-template-columns: 72px minmax(0, 1fr) 96px; align-content: start; align-items: start; }
  .option-row > img { width: 64px; height: 64px; object-fit: contain; border: 1px solid var(--line); border-radius: var(--radius-compact); background: var(--surface); }
  .option-row__details { min-width: 0; }
  .option-row__price { color: var(--ink) !important; font-weight: 700; font-variant-numeric: tabular-nums; }
  .option-empty { padding: var(--space-4); }
  .option-loading { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-4); color: var(--muted); font-size: 12px; }
</style>
