<script>
  import { onMount } from "svelte";
  import { requestJson } from "../api.js";
  import { getAllEstimates, getAppState, getCatalogCache, getEstimate, putAppState, putCatalogCache, putEstimate } from "../lib/db.js";
  import { syncPendingEstimates } from "../lib/sync.js";

  let { search = "", onSearch = () => {}, onFailure = () => {}, onSynced = () => {} } = $props();
  const PAGE_SIZE = 30;
  const KOREANET = "주식회사 코리아넷";
  // Cards are uniform-height (virtualisation math depends on it), so the row
  // height is derived from how many rows the widest attribute set needs at the
  // currently measured card width. Guessing from panel state alone clipped
  // attributes whenever the window was narrow.
  const CARD_BASE_HEIGHT = 108;
  const ATTRIBUTE_ROW_HEIGHT = 48;
  const ATTRIBUTE_COLUMN_MIN = 140;
  const ATTRIBUTE_COLUMN_GAP = 16;
  const OPTION_ROW_HEIGHT = 112;
  const OPTION_VIEWPORT_HEIGHT = 520;
  const OVERSCAN = 4;
  const RELATION_KINDS = ["selection", "additional", "construction"];
  const RELATION_LABELS = { selection: "선택품목", additional: "추가선택품목", construction: "공사" };
  const emptyPage = () => ({ items: [], page: 1, page_count: 1, total_count: 0 });
  let sort = $state("price_asc");
  let page = $state(1);
  let result = $state(emptyPage());
  let selected = $state(null);
  let options = $state({ selection: emptyPage(), additional: emptyPage(), construction: emptyPage() });
  let optionPages = $state({ selection: 1, additional: 1, construction: 1 });
  let optionLoading = $state({ selection: false, additional: false, construction: false });
  let relationSearch = $state({ selection: "", additional: "", construction: "" });
  const relationTimers = { selection: null, additional: null, construction: null };
  let loading = $state(false);
  let error = $state("");
  let listElement;
  let gridElement = $state();
  let cardWidth = $state(0);
  let optionElement = $state();
  let activeKind = $state("selection");
  let restored = $state(false);
  let requestVersion = 0;
  const optionRequestVersions = { selection: 0, additional: 0, construction: 0 };
  let catalogScrollTop = $state(0);
  let optionScrollTop = $state({ selection: 0, additional: 0, construction: 0 });
  let loadedSearch = null;
  let loadedSort = null;
  const catalogKey = (requestedPage) => `catalog:v3:${KOREANET}:${search}:${sort}:${requestedPage}`;
  const optionKey = (kind, query, requestedPage) => `relations:v3:${KOREANET}:${kind}:${query}:${sort}:${requestedPage}`;
  const maxAttributeCount = $derived(
    result.items.reduce((most, item) => Math.max(most, (item.attributes ?? []).length), 0),
  );
  const attributeColumns = $derived.by(() => {
    const details = cardWidth - 32 - 3 - (selected ? 132 : 150) - 12 - 72 - 12;
    if (details <= 0) return 3;
    const fit = Math.floor(
      (details + ATTRIBUTE_COLUMN_GAP) / (ATTRIBUTE_COLUMN_MIN + ATTRIBUTE_COLUMN_GAP),
    );
    return Math.max(1, fit);
  });
  const catalogRowHeight = $derived(
    CARD_BASE_HEIGHT
      + Math.max(1, Math.ceil(maxAttributeCount / attributeColumns)) * ATTRIBUTE_ROW_HEIGHT,
  );
  const catalogWindow = $derived(windowFor(result.items, catalogScrollTop, catalogRowHeight, 560));
  const activeOptions = $derived(options[activeKind]);
  const activeWindow = $derived(
    windowFor(activeOptions.items, optionScrollTop[activeKind], OPTION_ROW_HEIGHT, OPTION_VIEWPORT_HEIGHT),
  );

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
      relationSearch: { ...relationSearch },
      selectedProductId: selected?.product_id ?? null,
      scrollTop: catalogScrollTop,
      optionScrollTop: { ...optionScrollTop },
      activeKind,
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
      const online = await requestJson(`/api/catalog/products?company_name=${encodeURIComponent(KOREANET)}&q=${encodeURIComponent(search)}&sort=${sort}&page=${requestedPage}&page_size=${PAGE_SIZE}`);
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
    const query = relationSearch[kind].trim();
    const key = optionKey(kind, query, requestedPage);
    const cached = await getCatalogCache(key).catch(() => null);
    if (cached && version === optionRequestVersions[kind] && selected) {
      options = { ...options, [kind]: mergeOptionPage(options[kind], cached, requestedPage) };
    }
    try {
      const online = await requestJson(`/api/catalog/relations?company_name=${encodeURIComponent(KOREANET)}&category=${kind}&q=${encodeURIComponent(query)}&sort=${sort}&page=${requestedPage}&page_size=${PAGE_SIZE}`);
      if (version === optionRequestVersions[kind] && selected) {
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
  async function select(product, restoredPages = { selection: 1, additional: 1, construction: 1 }) {
    selected = product;
    options = { selection: emptyPage(), additional: emptyPage(), construction: emptyPage() };
    optionPages = { selection: 1, additional: 1, construction: 1 };
    relationSearch = { selection: "", additional: "", construction: "" };
    optionScrollTop = { selection: 0, additional: 0, construction: 0 };
    activeKind = "selection";
    await saveView();
    await Promise.all(RELATION_KINDS.map(async (kind) => {
      const lastPage = Math.max(1, restoredPages[kind] ?? 1);
      for (let requestedPage = 1; requestedPage <= lastPage; requestedPage += 1) {
        optionPages = { ...optionPages, [kind]: requestedPage };
        await loadOptions(kind, requestedPage);
      }
    }));
  }
  function closeOptions() {
    for (const kind of RELATION_KINDS) optionRequestVersions[kind] += 1;
    selected = null;
    options = { selection: emptyPage(), additional: emptyPage(), construction: emptyPage() };
    optionPages = { selection: 1, additional: 1, construction: 1 };
    relationSearch = { selection: "", additional: "", construction: "" };
    optionScrollTop = { selection: 0, additional: 0, construction: 0 };
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
  function changeRelationSearch(kind, event) {
    relationSearch = { ...relationSearch, [kind]: event.currentTarget.value };
    options = { ...options, [kind]: emptyPage() };
    optionPages = { ...optionPages, [kind]: 1 };
    optionScrollTop = { ...optionScrollTop, [kind]: 0 };
    clearTimeout(relationTimers[kind]);
    relationTimers[kind] = setTimeout(() => void loadOptions(kind, 1), 80);
  }
  function scrollCatalog() {
    catalogScrollTop = listElement.scrollTop;
    void saveView();
    if (!loading && page < result.page_count && listElement.scrollTop + listElement.clientHeight >= listElement.scrollHeight - 160) {
      page += 1;
      void loadCatalog(page);
    }
  }
  function scrollOptions() {
    const element = optionElement;
    const kind = activeKind;
    if (!element) return;
    optionScrollTop = { ...optionScrollTop, [kind]: element.scrollTop };
    void saveView();
    if (!optionLoading[kind] && optionPages[kind] < options[kind].page_count && element.scrollTop + element.clientHeight >= element.scrollHeight - 120) {
      const nextPage = optionPages[kind] + 1;
      optionPages = { ...optionPages, [kind]: nextPage };
      void loadOptions(kind, nextPage);
    }
  }
  function showKind(kind) {
    if (activeKind === kind) return;
    activeKind = kind;
    void saveView();
    requestAnimationFrame(() => {
      if (optionElement) optionElement.scrollTop = optionScrollTop[kind] ?? 0;
    });
  }
  function relationStatus(item) {
    if (!selected) return "";
    if (item.parent_product_id === selected.product_id) return `연결됨 · 본품 ${selected.name} (${selected.product_id})`;
    return `다른 본품 · ${item.parent_name || "본품 정보 없음"} (${item.parent_product_id})`;
  }
  function isRelated(item) { return selected && item.parent_product_id === selected.product_id; }

  onMount(() => {
    const observer = new ResizeObserver(([entry]) => { cardWidth = entry.contentRect.width; });
    if (gridElement) {
      cardWidth = gridElement.getBoundingClientRect().width;
      observer.observe(gridElement);
    }
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
          if (item) await select(item, state.optionPages ?? { selection: 1, additional: 1, construction: 1 });
        }
        relationSearch = { ...relationSearch, ...(state.relationSearch ?? {}) };
        if (RELATION_KINDS.includes(state.activeKind)) activeKind = state.activeKind;
        catalogScrollTop = state.scrollTop ?? 0;
        optionScrollTop = typeof state.optionScrollTop === "object" ? { selection: 0, additional: 0, construction: 0, ...state.optionScrollTop } : { selection: state.optionScrollTop ?? 0, additional: state.optionScrollTop ?? 0, construction: state.optionScrollTop ?? 0 };
        requestAnimationFrame(() => {
          if (listElement) listElement.scrollTop = catalogScrollTop;
          if (optionElement) optionElement.scrollTop = optionScrollTop[activeKind] ?? 0;
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
    return () => observer.disconnect();
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
    {:else}본품 {result.total_count.toLocaleString()}건{/if}
  </p>
  <div class:selected-column={selected} class="catalog-columns">
    <div class="catalog-scroll" bind:this={listElement} onscroll={scrollCatalog} aria-busy={loading}>
      <div class="catalog-grid" bind:this={gridElement} style:--catalog-row={`${catalogRowHeight}px`}>
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
            <div class="catalog-card__actions"><a class="g2b-link" href={item.g2b_url}>나라장터에서 보기</a><button class="button button--secondary" type="button" onclick={() => add(item, "main")}>리스트에 추가</button></div>
          </article>
        {/each}
        <div class="virtual-spacer" style:height={`${catalogWindow.bottom}px`}></div>
      </div>
      {#if !loading && result.items.length === 0}<div class="empty-state"><h2>검색 결과 없음</h2><p>다른 검색어를 입력해 보세요.</p></div>{/if}
    </div>
    {#if selected}
      <aside class="option-panel" aria-labelledby="option-title">
        <header class="option-panel__header"><div><span class="option-panel__eyebrow">선택한 본품</span><h2 id="option-title">{selected.name} · {selected.product_id}</h2></div><button class="button--secondary" type="button" onclick={closeOptions}>닫기</button></header>
        <div class="option-tabs" role="tablist" aria-label="연결된 품목 유형">
          {#each RELATION_KINDS as kind}
            <button
              class="option-tab"
              type="button"
              role="tab"
              id={`option-tab-${kind}`}
              aria-selected={activeKind === kind}
              aria-controls="option-tabpanel"
              onclick={() => showKind(kind)}
            >{RELATION_LABELS[kind]}<span>{options[kind].total_count.toLocaleString()}</span></button>
          {/each}
        </div>
        <div class="option-body" role="tabpanel" id="option-tabpanel" aria-labelledby={`option-tab-${activeKind}`}>
          <div class="option-group__header">
            <label>
              <span class="visually-hidden">{RELATION_LABELS[activeKind]} 검색</span>
              <input type="search" value={relationSearch[activeKind]} placeholder={`${RELATION_LABELS[activeKind]} 검색`} oninput={(event) => changeRelationSearch(activeKind, event)} />
            </label>
          </div>
          <div class="option-scroll" bind:this={optionElement} onscroll={scrollOptions} aria-busy={optionLoading[activeKind]}>
            <div class="virtual-spacer" style:height={`${activeWindow.top}px`}></div>
            {#each activeWindow.items as item (`${item.relation_id}:${item.product_id}`)}
              <article class:option-row--connected={isRelated(item)} class="option-row">
                <img src={item.image_url || "/static/product-placeholder.svg"} alt={`${item.name} 상품 이미지`} onerror={(event) => { event.currentTarget.onerror = null; event.currentTarget.src = "/static/product-placeholder.svg"; }} />
                <div class="option-row__details"><strong>{item.name}</strong><span>{item.spec.replace(/\s+:\s+(?=[\d,])/g, " : ")}</span><span class="relation-status" class:relation-status--connected={isRelated(item)}>{relationStatus(item)}</span><span class="option-row__price">{item.price_won?.toLocaleString()}원 / {item.unit}</span></div>
                <div class="catalog-card__actions"><a class="g2b-link" href={item.g2b_url}>나라장터에서 보기</a><button class="button button--secondary" type="button" onclick={() => add(item, "option", selected)}>리스트에 추가</button></div>
              </article>
            {/each}
            <div class="virtual-spacer" style:height={`${activeWindow.bottom}px`}></div>
            {#if optionLoading[activeKind] && activeOptions.items.length === 0}
              <div class="option-loading" role="status"><span class="loading-spinner" aria-hidden="true"></span><span>{RELATION_LABELS[activeKind]} 불러오는 중</span></div>
            {/if}
            {#if !optionLoading[activeKind] && activeOptions.items.length === 0}<p class="state-message option-empty">{RELATION_LABELS[activeKind]} 없음.</p>{/if}
          </div>
        </div>
      </aside>
    {/if}
  </div>
</section>

<style>
  .catalog-card__select { align-self: stretch; align-items: center; }
  .catalog-columns.selected-column .catalog-card { grid-template-columns: minmax(0, 1fr) 132px; }
  .option-panel { display: grid; min-block-size: 0; grid-template-rows: auto auto minmax(0, 1fr); }
  .option-panel__header { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: var(--space-3); padding: var(--space-3) var(--space-4); border-block-end: 1px solid var(--line); background: var(--surface-subtle); }
  .option-panel__header h2 { min-width: 0; margin: 0; font-size: 15px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .option-panel__header button { min-height: 36px; padding-inline: var(--space-3); }
  .option-panel__eyebrow { display: block; color: var(--muted); font-size: 11px; }

  .option-tabs { display: flex; gap: var(--space-1); padding: var(--space-2) var(--space-3) 0; border-block-end: 1px solid var(--line); }
  .option-tab {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    min-height: 38px;
    padding-inline: var(--space-3);
    border: 0;
    border-block-end: 2px solid transparent;
    border-radius: var(--radius-compact) var(--radius-compact) 0 0;
    color: var(--muted);
    background: transparent;
    font-size: 13px;
    font-weight: 500;
    white-space: nowrap;
  }
  .option-tab span {
    padding-inline: 6px;
    border-radius: 999px;
    color: var(--muted);
    background: var(--surface-subtle);
    font-size: 11px;
    font-variant-numeric: tabular-nums;
  }
  .option-tab:hover { color: var(--ink); background: var(--surface-subtle); }
  .option-tab[aria-selected="true"] { border-block-end-color: var(--accent); color: var(--accent-dark); background: transparent; }
  .option-tab[aria-selected="true"] span { color: var(--accent-dark); background: var(--surface-selected); }

  .option-body { display: grid; min-block-size: 0; grid-template-rows: auto minmax(0, 1fr); }
  .option-group__header { padding: var(--space-2) var(--space-3); border-block-end: 1px solid var(--line); }
  .option-group__header label { margin: 0; }
  .option-group__header input { min-height: 34px; padding-inline: var(--space-3); font-size: 12px; }
  .option-panel .option-scroll { block-size: auto; min-height: 0; padding-inline-end: 0; }
  .option-row { display: grid; grid-template-columns: 56px minmax(0, 1fr) 112px; block-size: 112px; align-content: center; align-items: center; padding: var(--space-2) var(--space-3); }
  .option-row > img { width: 64px; height: 64px; object-fit: contain; border: 1px solid var(--line); border-radius: var(--radius-compact); background: var(--surface); }
  .option-row__details { min-width: 0; }
  .option-row__details > strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .option-row__details > span { display: block; margin-block-start: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .relation-status { color: var(--muted) !important; font-size: 11px !important; }
  .relation-status--connected { color: var(--accent) !important; font-weight: 600; }
  .option-row--connected { background: var(--surface-selected); }
  .option-row__price { color: var(--ink) !important; font-weight: 700; font-variant-numeric: tabular-nums; }
  .option-row .catalog-card__actions { gap: var(--space-1); }
  .option-row .catalog-card__actions .button, .option-row .g2b-link { min-height: 32px; padding-inline: var(--space-2); font-size: 11px; }
  .option-empty { padding: var(--space-4); }
  .option-loading { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-4); color: var(--muted); font-size: 12px; }
</style>
