<script>
  import { onDestroy, onMount } from "svelte";
  import { requestJson } from "../api.js";
  import { deleteEstimate, getAppState, getCatalogCache, getEstimate, putAppState, putCatalogCache, putEstimate, putSyncedEstimate } from "../lib/db.js";
  import { conciseSpec, documentItemName, documentUnit } from "../lib/spec.js";
  import { syncPendingEstimates } from "../lib/sync.js";

  let { id, onNavigate = () => {}, onFailure = () => {}, onSynced = () => {} } = $props();
  const KOREANET = "주식회사 코리아넷";
  const OPTION_GROUP_LABELS = {
    selection: "선택품목",
    additional: "추가선택품목",
    construction: "공사",
  };
  const OPTION_GROUPS = Object.keys(OPTION_GROUP_LABELS);
  let document = $state(null);
  let remote = $state(null);
  let error = $state("");
  let loading = $state(true);
  let notFound = $state(false);
  let productSearch = $state("");
  let productResults = $state([]);
  let productSort = $state("price_asc");
  let productTotal = $state(0);
  let selectedProduct = $state(null);
  let selectedOptions = $state([]);
  let searching = $state(false);
  let optionsLoading = $state(false);
  let searchError = $state("");
  let searchOpen = $state(false);
  let comparisonLoading = $state(false);
  let copyStatus = $state("");
  let specTooltip = $state(null);
  let searchAnchor = $state();
  let editingTitle = $state(false);
  let titleDraft = $state("");
  let searchTimer;
  let copyTimer;
  let searchVersion = 0;
  let optionsVersion = 0;
  const money = (value) => Number(value ?? 0).toLocaleString();

  function newId() {
    return [...crypto.getRandomValues(new Uint8Array(16))]
      .map((value) => value.toString(16).padStart(2, "0"))
      .join("");
  }
  function compactCompanyName(value) {
    return String(value ?? "").replace(/^(?:주식회사|\(주\)|㈜)\s*/u, "").trim();
  }
  function productTitle(item) {
    const parts = String(item.spec ?? "").split(",").map((part) => part.trim()).filter(Boolean);
    const purpose = item.attributes?.find((attribute) => attribute.name === "용도")?.value
      ?? (parts.length > 3 ? parts.at(-1) : "");
    return [...new Set([
      item.name,
      parts[1] || compactCompanyName(item.company_name),
      parts[2],
      purpose,
    ].filter(Boolean))].join(", ");
  }
  function optionGroup(item) {
    if (/공사/u.test(`${item.name} ${item.spec}`)) return "construction";
    return item.relation_kind === "component" ? "selection" : "additional";
  }
  function optionsFor(group) {
    return selectedOptions.filter((item) => optionGroup(item) === group);
  }
  function rowAttributes(line, details) {
    if (line.line_kind !== "option") return details?.attributes ?? [];
    if (!/카메라/u.test(line.item_name_snapshot)) return [];
    const lineIndex = document.lines.findIndex((candidate) => candidate.id === line.id);
    const precedingMain = document.lines.slice(0, lineIndex).findLast((candidate) => candidate.line_kind === "main");
    return remote?.lines?.find((candidate) => candidate.id === precedingMain?.id)?.attributes
      ?? details?.attributes
      ?? [];
  }
  function comparisonAttributes(comparison, line, details) {
    if (line.line_kind === "option") {
      return /카메라/u.test(line.item_name_snapshot) ? rowAttributes(line, details) : [];
    }
    const itemName = documentItemName(line.item_name_snapshot, line.spec_snapshot);
    return itemName === line.item_name_snapshot ? comparison.attributes : [];
  }
  function comparisonSpec(comparison, line, details) {
    const itemName = documentItemName(line.item_name_snapshot, line.spec_snapshot);
    return conciseSpec(
      comparison.spec_snapshot,
      comparisonAttributes(comparison, line, details),
      itemName,
    );
  }
  function showSpecTooltip(event, spec, attributes = []) {
    const rect = event.currentTarget.getBoundingClientRect();
    const above = rect.bottom > globalThis.innerHeight * 0.65;
    specTooltip = {
      spec,
      attributes,
      above,
      left: Math.max(8, Math.min(rect.left, globalThis.innerWidth - 520)),
      top: above ? rect.top - 8 : rect.bottom + 8,
    };
  }
  function hideSpecTooltip() {
    specTooltip = null;
  }
  function hideSpecTooltipOnEscape(event) {
    if (event.key === "Escape") hideSpecTooltip();
  }
  function comparisonFor(details, slot) {
    return details?.comparisons?.find((candidate) => candidate.slot === slot);
  }
  function appliedPrice(line, details) {
    return comparisonFor(details, "A")?.price_won_snapshot ?? line.unit_price_won_snapshot;
  }
  function localDocument(serverDocument) {
    return {
      id: serverDocument.id,
      title: serverDocument.title,
      lines: serverDocument.lines.map(({
        id: lineId,
        line_kind,
        product_id,
        parent_product_id,
        relation_id,
        offer_operation,
        offer_key,
        item_name_snapshot,
        spec_snapshot,
        company_snapshot,
        unit_snapshot,
        unit_price_won_snapshot,
        quantity,
      }) => ({
        id: lineId,
        line_kind,
        product_id,
        parent_product_id,
        relation_id,
        offer_operation,
        offer_key,
        item_name_snapshot,
        spec_snapshot,
        company_snapshot,
        unit_snapshot,
        unit_price_won_snapshot,
        quantity: String(quantity),
      })),
    };
  }
  async function load() {
    loading = true;
    notFound = false;
    error = "";
    const local = await getEstimate(id);
    if (local?.deleted) {
      if ((await getAppState("activeEstimateId")) === id) await putAppState("activeEstimateId", null);
      loading = false;
      return;
    }
    document = local?.document ?? null;
    try {
      remote = await requestJson(`/api/estimates/${id}`);
      if (!local || !local.pendingSync) {
        document = localDocument(remote);
        await putSyncedEstimate($state.snapshot(document));
      }
      await putAppState("activeEstimateId", id);
    } catch (caught) {
      if (caught?.status === 404 && local) {
        await putAppState("activeEstimateId", id);
      } else if (caught?.status === 404) {
        document = null;
        notFound = true;
        if ((await getAppState("activeEstimateId")) === id) await putAppState("activeEstimateId", null);
      } else {
        onFailure(caught);
        error = document ? "오프라인 편집 중: 서버 비교 결과는 연결 후 표시됨." : "문서를 불러오지 못했음.";
      }
    } finally {
      loading = false;
    }
  }
  async function settleSync(deleted = false) {
    comparisonLoading = !deleted;
    try {
      await syncPendingEstimates(globalThis.fetch, onSynced);
      const saved = await getEstimate(id);
      if (saved?.error) {
        error = `동기화 오류: ${saved.error}`;
        onFailure({ offline: true });
        return;
      }
      if (deleted) return;
      remote = await requestJson(`/api/estimates/${id}`);
      error = "";
    } catch (caught) {
      onFailure(caught);
    } finally {
      comparisonLoading = false;
    }
  }
  async function save() {
    if (!document) return;
    if (document.lines.length === 0) {
      await deleteEstimate(id);
      if ((await getAppState("activeEstimateId")) === id) await putAppState("activeEstimateId", null);
      void settleSync(true);
      return;
    }
    await putEstimate($state.snapshot(document));
    void settleSync();
  }
  function remove(lineId) {
    document = { ...document, lines: document.lines.filter((line) => line.id !== lineId) };
    void save();
  }
  function startEditTitle() {
    if (!document) return;
    titleDraft = document.title;
    editingTitle = true;
  }
  function commitTitle() {
    const trimmed = titleDraft.trim();
    editingTitle = false;
    if (!trimmed || trimmed === document.title) return;
    document = { ...document, title: trimmed };
    void save();
  }
  function cancelEditTitle() {
    editingTitle = false;
  }
  function handleTitleKeydown(event) {
    if (event.key === "Enter") event.currentTarget.blur();
    if (event.key === "Escape") { cancelEditTitle(); event.currentTarget.blur(); }
  }
  async function searchProducts(query) {
    const version = ++searchVersion;
    searching = true;
    searchError = "";
    const cacheKey = `document-products:v4:${query}:${productSort}`;
    const cached = await getCatalogCache(cacheKey).catch(() => null);
    if (cached && version === searchVersion) {
      productResults = cached.items;
      productTotal = cached.total_count;
    }
    try {
      const queryParams = `preferred_company_name=${encodeURIComponent(KOREANET)}&q=${encodeURIComponent(query)}&sort=${productSort}&page=1&page_size=100`;
      const result = await requestJson(`/api/catalog/products?${queryParams}`);
      if (version === searchVersion) {
        productResults = result.items;
        productTotal = result.total_count;
        if (!productResults.length) searchError = "일치하는 물품 없음.";
      }
      try { await putCatalogCache(cacheKey, result); } catch {}
    } catch (caught) {
      if (version === searchVersion) {
        onFailure(caught);
        if (!cached) {
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
    searchTimer = setTimeout(() => void searchProducts(productSearch.trim()), 30);
  }
  function changeProductSort() {
    closeSelectedProduct();
    void searchProducts(productSearch.trim());
  }
  async function selectProduct(item) {
    const version = ++optionsVersion;
    selectedProduct = item;
    selectedOptions = [];
    optionsLoading = true;
    searchError = "";
    const cacheKey = `document-product-options:v2:${item.product_id}`;
    const cached = await getCatalogCache(cacheKey).catch(() => null);
    if (cached && version === optionsVersion) selectedOptions = cached.items;
    try {
      const firstPage = await requestJson(`/api/catalog/products/${item.product_id}/options?page=1&page_size=100`);
      const remainingPages = await Promise.all(
        Array.from(
          { length: firstPage.page_count - 1 },
          (_, index) => requestJson(`/api/catalog/products/${item.product_id}/options?page=${index + 2}&page_size=100`),
        ),
      );
      const result = { ...firstPage, items: [...firstPage.items, ...remainingPages.flatMap((page) => page.items)] };
      if (version === optionsVersion) selectedOptions = result.items;
      try { await putCatalogCache(cacheKey, result); } catch {}
    } catch (caught) {
      if (version === optionsVersion) {
        onFailure(caught);
        if (!cached) searchError = "연결된 품목을 불러오지 못했음.";
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
  function openProductSearch() {
    searchOpen = true;
    globalThis.requestAnimationFrame(() => globalThis.document.getElementById("document-product-search")?.focus());
  }
  function handleSearchKeydown(event) {
    if (event.key !== "Escape") return;
    searchOpen = false;
    event.currentTarget.blur();
  }
  function closeSearchOnOutsideClick(event) {
    if (searchOpen && searchAnchor && !searchAnchor.contains(event.target)) searchOpen = false;
  }
  function addProduct(item) {
    if (document.lines.length >= 9) {
      searchError = "문서에는 품목을 최대 9개까지 추가할 수 있음.";
      return;
    }
    if (item.relation_id && document.lines.some((line) => line.relation_id === item.relation_id)) {
      searchError = "이미 추가된 하위 품목임.";
      return;
    }
    document = {
      ...document,
      lines: [...document.lines, {
        id: newId(),
        line_kind: item.relation_id ? "option" : "main",
        product_id: item.product_id,
        parent_product_id: item.parent_product_id ?? null,
        relation_id: item.relation_id ?? null,
        offer_operation: null,
        offer_key: null,
        item_name_snapshot: documentItemName(item.name, item.spec),
        spec_snapshot: item.spec,
        company_snapshot: item.company_name,
        unit_snapshot: documentUnit(item.name, item.unit, item.spec),
        unit_price_won_snapshot: item.price_won,
        quantity: "1",
      }],
    };
    searchError = "";
    void save();
  }
  function tableTsv(includeSequence) {
    const cell = (value) => {
      const normalized = String(value ?? "").replace(/[\t\r\n]+/g, " ");
      return /^\s*[=+\-@]/.test(normalized) ? `'${normalized}` : normalized;
    };
    const rows = [
      [
        "연번", "품명", "규격", "단위", "적용단가",
        "A사 적용회사", "A사 규격", "A사 물품식별번호", "A사 단가",
        "B사 회사명", "B사 규격", "B사 물품식별번호", "B사 단가",
        "C사 회사명", "C사 규격", "C사 물품식별번호", "C사 단가", "비고",
      ],
      ...(document?.lines ?? []).map((line, index) => {
        const details = remote?.lines?.find((candidate) => candidate.id === line.id);
        const comparisons = ["A", "B", "C"].flatMap((slot) => {
          const comparison = comparisonFor(details, slot);
          return comparison ? [
            compactCompanyName(comparison.company_snapshot),
            comparisonSpec(comparison, line, details),
            comparison.product_id,
            comparison.price_won_snapshot,
          ] : ["", "", "", ""];
        });
        return [
          index + 1,
          documentItemName(line.item_name_snapshot, line.spec_snapshot),
          conciseSpec(line.spec_snapshot, rowAttributes(line, details), line.item_name_snapshot),
          documentUnit(line.item_name_snapshot, line.unit_snapshot, line.spec_snapshot),
          appliedPrice(line, details),
          ...comparisons,
          "",
        ];
      }),
    ];
    return rows
      .map((row) => (includeSequence ? row : row.slice(1)).map(cell).join("\t"))
      .join("\n");
  }
  async function copyTable(event) {
    const button = event.currentTarget;
    copyStatus = "";
    let buffer;
    try {
      const text = tableTsv(false);
      if (globalThis.navigator.clipboard?.writeText) {
        await globalThis.navigator.clipboard.writeText(text);
      } else {
        buffer = Object.assign(globalThis.document.createElement("textarea"), {
          value: text,
          className: "visually-hidden",
        });
        globalThis.document.body.append(buffer);
        buffer.select();
        if (!globalThis.document.execCommand("copy")) throw new Error("copy failed");
      }
      copyStatus = "복사됨";
    } catch {
      copyStatus = "복사 실패";
    } finally {
      buffer?.remove();
      button.focus();
      clearTimeout(copyTimer);
      copyTimer = setTimeout(() => copyStatus = "", 1600);
    }
  }
  function copyTsv() {
    const blob = new Blob([tableTsv(true)], {
      type: "text/tab-separated-values;charset=utf-8",
    });
    const anchor = Object.assign(globalThis.document.createElement("a"), {
      href: URL.createObjectURL(blob),
      download: `${document?.title ?? "document"}.tsv`,
    });
    anchor.click();
    URL.revokeObjectURL(anchor.href);
  }

  onMount(() => {
    globalThis.document.addEventListener("pointerdown", closeSearchOnOutsideClick);
    void load();
    void searchProducts("");
    return () => globalThis.document.removeEventListener("pointerdown", closeSearchOnOutsideClick);
  });
  onDestroy(() => {
    clearTimeout(searchTimer);
    clearTimeout(copyTimer);
  });
</script>

<header class="page-header">
  {#if editingTitle}
    <input
      class="page-title-input"
      type="text"
      bind:value={titleDraft}
      onblur={commitTitle}
      onkeydown={handleTitleKeydown}
      aria-label="문서 제목"
    />
  {:else}
    <button
      class="page-title-edit"
      type="button"
      onclick={startEditTitle}
      aria-label={`문서 제목 편집: ${document?.title ?? "문서 작성"}`}
      disabled={!document}
    >
      <h1>{document?.title ?? "문서 작성"}</h1>
    </button>
  {/if}
  <p class="route-id visually-hidden">문서 ID: {id}</p>
</header>
{#if document}
  <section class="page-actions">
    <button class="button--secondary document-back" type="button" onclick={() => onNavigate("/estimates")}>닫기</button>
    <button class="button" type="button" onclick={openProductSearch}>내역 추가</button>
    <button class="button" type="button" onclick={copyTable}>{copyStatus || "표 복사"}</button>
    <button class="button--secondary" type="button" onclick={copyTsv}>TSV 내려받기</button>
    {#if remote?.export_ready}<a class="button button--secondary" href={`/estimates/${id}/export.xlsx`}>XLSX 내려받기</a>{/if}
  </section>
  {#if error}<p class="state-message state-message--error" role="status">{error}</p>{/if}
  <div class="document-workspace">
  <section class="panel catalog-workspace document-catalog" aria-label="물품 검색">
    <div class="document-search-anchor" bind:this={searchAnchor}>
      <div class="catalog-controls">
        <label for="document-product-search">
          <span>검색어</span>
          <input
            id="document-product-search"
            type="search"
            autocomplete="off"
            placeholder="물품명, 규격 또는 업체명"
            value={productSearch}
            aria-controls="document-search-results"
            onfocus={() => searchOpen = true}
            onkeydown={handleSearchKeydown}
            oninput={(event) => { closeSelectedProduct(); queueSearch(event); }}
          />
        </label>
        <label for="document-product-sort">
          <span>정렬</span>
          <select id="document-product-sort" bind:value={productSort} onchange={changeProductSort}>
            <option value="price_asc">낮은 가격순</option>
            <option value="price_desc">높은 가격순</option>
            <option value="name_asc">품명순</option>
            <option value="product_id_asc">식별번호순</option>
          </select>
        </label>
      </div>
      <div id="document-search-results" class="document-search-overlay" class:is-open={searchOpen} role="region" aria-label="물품 검색 결과">
          <div class="document-search-overlay__header">
            <p class="catalog-summary" aria-live="polite">
              {#if searching}<span class="loading-label"><span class="loading-spinner" aria-hidden="true"></span>검색 중</span>
              {:else}본품 검색 결과 {productTotal.toLocaleString()}건{/if}
            </p>
            <button class="button--secondary" type="button" onclick={() => searchOpen = false}>닫기</button>
          </div>
          {#if searchError}<p class="state-message state-message--error" role="status">{searchError}</p>{/if}
          <div class:selected-column={selectedProduct} class="document-search-columns">
            <div class="document-result-scroll" aria-busy={searching}>
              <div class="catalog-grid">
              {#if searching && productResults.length === 0}
                {#each [1, 2] as placeholder}
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
              {#each productResults as item (item.product_id)}
                <article class="catalog-card">
                  <button class="catalog-card__select document-result-card__body" type="button" aria-pressed={selectedProduct?.product_id === item.product_id} onclick={() => selectProduct(item)}>
                    <img loading="lazy" src={item.image_url || "/static/product-placeholder.svg"} alt={`${item.name} 상품 이미지`} onerror={(event) => { event.currentTarget.onerror = null; event.currentTarget.src = "/static/product-placeholder.svg"; }} />
                    <div class="catalog-card__details">
                      <strong>{productTitle(item)}</strong>
                      <span class="catalog-card__price">{money(item.price_won)}원 / {item.unit}</span>
                      <span>{item.contract_method} · {item.delivery_condition} · 납기 {item.delivery_days}일 · {item.contract_end_date}</span>
                      {#if item.attributes?.length}
                        <dl class="attribute-list">{#each item.attributes as attribute}<div><dt>{attribute.name}</dt><dd>{attribute.value}{attribute.unit}</dd></div>{/each}</dl>
                      {/if}
                    </div>
                  </button>
                  <div class="catalog-card__actions">
                    <a class="g2b-link" href={item.g2b_url}>나라장터에서 보기</a>
                    <button class="button button--secondary" type="button" onclick={() => addProduct(item)}>리스트에 추가</button>
                  </div>
                </article>
              {/each}
              </div>
            </div>
            {#if selectedProduct}
              <aside class="document-option-panel" aria-label="연결된 하위 품목">
                <header class="document-option-panel__header">
                  <div><span>선택한 본품</span><h2>{selectedProduct.name} · {selectedProduct.product_id}</h2></div>
                  <button class="button--secondary" type="button" onclick={closeSelectedProduct}>닫기</button>
                </header>
                <div class="document-option-groups">
                  {#each OPTION_GROUPS as group}
                    <section class="document-option-group">
                      <h3>{OPTION_GROUP_LABELS[group]} <span>{optionsFor(group).length.toLocaleString()}건</span></h3>
                      <div class="document-option-scroll" aria-busy={optionsLoading}>
                        {#if optionsLoading}<p class="option-loading"><span class="loading-spinner" aria-hidden="true"></span>불러오는 중</p>
                        {:else if optionsFor(group).length === 0}<p class="option-empty">연결된 품목 없음.</p>
                        {:else}
                          {#each optionsFor(group) as item (item.relation_id)}
                            <article class="document-option-row">
                              <img loading="lazy" src={item.image_url || "/static/product-placeholder.svg"} alt={`${item.name} 상품 이미지`} onerror={(event) => { event.currentTarget.onerror = null; event.currentTarget.src = "/static/product-placeholder.svg"; }} />
                              <div><strong>{item.name}</strong><span>{item.spec}</span><span class="option-row__price">{money(item.price_won)}원 / {item.unit}</span></div>
                              <div class="catalog-card__actions"><a class="g2b-link" href={item.g2b_url}>나라장터에서 보기</a><button class="button button--secondary" type="button" onclick={() => addProduct(item)}>리스트에 추가</button></div>
                            </article>
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

  <section class="document-sheet" aria-label="단가조사 문서 편집기">
    <div class="document-table-wrap" aria-busy={loading || comparisonLoading} onscroll={hideSpecTooltip}>
      <table class="document-table">
        <colgroup>
          <col class="col-sequence" /><col class="col-name" /><col class="col-spec" /><col class="col-unit" /><col class="col-price" />
          {#each ["A", "B", "C"] as slot}<col class="col-company" /><col class="col-company-spec" /><col class="col-id" /><col class="col-price" />{/each}
          <col class="col-note" />
        </colgroup>
        <thead>
          <tr>
            <th class="document-no-copy" rowspan="2">연번</th>
            <th rowspan="2">품 명</th>
            <th rowspan="2">규 격</th>
            <th rowspan="2">단위</th>
            <th rowspan="2">적용단가</th>
            <th colspan="4">적용회사(A사)</th>
            <th colspan="4">B사</th>
            <th colspan="4">C사</th>
            <th rowspan="2">비 고</th>
          </tr>
          <tr>
            <th>적용회사</th><th>규격</th><th>물품식별번호</th><th>단가</th>
            <th>회사명</th><th>규격</th><th>물품식별번호</th><th>단가</th>
            <th>회사명</th><th>규격</th><th>물품식별번호</th><th>단가</th>
          </tr>
        </thead>
        <tbody>
          {#each document.lines as line, index (line.id)}
            {@const details = remote?.lines?.find((candidate) => candidate.id === line.id)}
            <tr>
              <td class="document-sequence document-no-copy">
                <span>{index + 1}</span>
                <button class="button--secondary" type="button" aria-label={`${line.item_name_snapshot} 행 삭제`} onclick={() => remove(line.id)}>삭제</button>
              </td>
              <td>{documentItemName(line.item_name_snapshot, line.spec_snapshot)}</td>
              <td>
                <button
                  type="button"
                  class="spec-tooltip-trigger"
                  aria-label={`${conciseSpec(line.spec_snapshot, rowAttributes(line, details), line.item_name_snapshot)}. 전체 규격: ${line.spec_snapshot}`}
                  onpointerenter={(event) => showSpecTooltip(event, line.spec_snapshot, rowAttributes(line, details))}
                  onpointerleave={hideSpecTooltip}
                  onfocus={(event) => showSpecTooltip(event, line.spec_snapshot, rowAttributes(line, details))}
                  onblur={hideSpecTooltip}
                  onkeydown={hideSpecTooltipOnEscape}
                >{conciseSpec(line.spec_snapshot, rowAttributes(line, details), line.item_name_snapshot)}</button>
              </td>
              <td class="document-center">{documentUnit(line.item_name_snapshot, line.unit_snapshot, line.spec_snapshot)}</td>
              <td class="document-number">{money(appliedPrice(line, details))}</td>
              {#each ["A", "B", "C"] as slot}
                {@const comparison = comparisonFor(details, slot)}
                <td class:document-baseline={slot === "A"}>
                  {#if comparison}{compactCompanyName(comparison.company_snapshot)}
                  {:else if loading || comparisonLoading}<span class="loading-placeholder loading-placeholder--short" aria-hidden="true"></span>{/if}
                </td>
                <td class:document-baseline={slot === "A"}>
                  {#if comparison}
                    <button
                      type="button"
                      class="spec-tooltip-trigger"
                      aria-label={`${comparisonSpec(comparison, line, details)}. 전체 규격: ${comparison.spec_snapshot}`}
                      onpointerenter={(event) => showSpecTooltip(event, comparison.spec_snapshot, comparisonAttributes(comparison, line, details))}
                      onpointerleave={hideSpecTooltip}
                      onfocus={(event) => showSpecTooltip(event, comparison.spec_snapshot, comparisonAttributes(comparison, line, details))}
                      onblur={hideSpecTooltip}
                      onkeydown={hideSpecTooltipOnEscape}
                    >{comparisonSpec(comparison, line, details)}</button>
                  {:else if loading || comparisonLoading}<span class="loading-placeholder loading-placeholder--text" aria-hidden="true"></span>{/if}
                </td>
                <td class:document-baseline={slot === "A"}>
                  {#if comparison}
                    <a
                      class="document-product-link"
                      href={comparison.g2b_url}
                      target="_blank"
                      rel="noreferrer"
                      aria-label={`${slot}사 물품식별번호 ${comparison.product_id} 나라장터에서 보기`}
                    >{comparison.product_id}</a>
                  {:else if loading || comparisonLoading}<span class="loading-placeholder loading-placeholder--short" aria-hidden="true"></span>{/if}
                </td>
                <td class:document-baseline={slot === "A"} class="document-number">
                  {#if comparison}{money(comparison.price_won_snapshot)}
                  {:else if loading || comparisonLoading}<span class="loading-placeholder loading-placeholder--short" aria-hidden="true"></span>{/if}
                </td>
              {/each}
              <td></td>
            </tr>
          {/each}
          {#if document.lines.length === 0}<tr class="document-empty-row"><td colspan="18"></td></tr>{/if}
        </tbody>
      </table>
    </div>
  </section>
  </div>
  {#if specTooltip}
    <aside
      id="full-spec-tooltip"
      class="spec-tooltip"
      class:spec-tooltip--above={specTooltip.above}
      style={`inset-inline-start: ${specTooltip.left}px; inset-block-start: ${specTooltip.top}px;`}
      role="tooltip"
    >
      <p class="spec-tooltip__title">전체 규격</p>
      <p>{specTooltip.spec}</p>
      {#if specTooltip.attributes?.length}
        <dl>
          {#each specTooltip.attributes as attribute}
            <div><dt>{attribute.name}</dt><dd>{attribute.value}{attribute.unit}</dd></div>
          {/each}
        </dl>
      {/if}
    </aside>
  {/if}
{:else if loading}
  <section class="empty-state" aria-busy="true">
    <h2 class="loading-label"><span class="loading-spinner" aria-hidden="true"></span>문서 불러오는 중</h2>
    <div class="loading-stack" aria-hidden="true">
      <span class="loading-placeholder loading-placeholder--title"></span>
      <span class="loading-placeholder loading-placeholder--text"></span>
      <span class="loading-placeholder loading-placeholder--short"></span>
    </div>
  </section>
{:else if notFound}
  <section class="empty-state"><h2>문서를 찾을 수 없음</h2><p>삭제되었거나 존재하지 않는 문서임.</p></section>
{:else}
  <section class="empty-state"><h2>문서를 불러오지 못했음</h2><p>{error || "연결을 확인한 뒤 다시 시도하세요."}</p></section>
{/if}

<style>
  .page-title-edit {
    all: unset;
    display: inline-block;
    cursor: text;
    border-radius: var(--radius-2, 6px);
    padding-inline: var(--space-1, 4px);
  }
  .page-title-edit:hover,
  .page-title-edit:focus-visible {
    outline: 2px solid var(--color-border-focus, #94a3b8);
    outline-offset: 2px;
  }
  .page-title-input {
    font: inherit;
    font-size: 1.5rem;
    font-weight: 700;
    line-height: 1.2;
    padding: 0;
    border: none;
    border-bottom: 2px solid var(--color-border-focus, #94a3b8);
    background: transparent;
    color: inherit;
    width: 100%;
    max-width: 32rem;
  }
  .page-title-input:focus {
    outline: none;
  }
  .state-message + .document-workspace {
    margin-block-start: var(--space-2);
  }

  /* Keep navigation away from the destructive-adjacent export cluster. */
  .document-back {
    margin-inline-end: auto;
  }

  .document-catalog,
  .document-sheet {
    margin-block-start: var(--space-4);
  }

  .document-workspace {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: var(--space-3);
  }

  .document-catalog {
    padding: var(--space-3);
  }

  .document-catalog .catalog-controls {
    grid-template-columns: minmax(0, 1fr) 112px;
    gap: var(--space-2);
  }

  .document-catalog .catalog-controls label {
    gap: var(--space-1);
  }

  .document-catalog .catalog-controls label > span {
    font-size: 11px;
  }

  .document-catalog .catalog-controls input,
  .document-catalog .catalog-controls select {
    min-block-size: 38px;
    padding-inline: var(--space-3);
    font-size: 12px;
  }

  .document-search-anchor {
    position: relative;
  }

  .document-search-overlay {
    position: absolute;
    inset-block-start: calc(100% + var(--space-2));
    inset-inline: 0;
    z-index: 10;
    display: grid;
    grid-template-rows: auto auto minmax(0, 1fr);
    block-size: min(620px, calc(100dvh - 220px));
    padding: var(--space-2);
    border: 1px solid var(--line);
    border-radius: var(--radius-surface);
    background: var(--surface);
    box-shadow: 0 var(--space-2) var(--space-6) color-mix(in srgb, var(--ink) 14%, transparent);
    visibility: hidden;
    opacity: 0;
    pointer-events: none;
  }

  .document-search-overlay.is-open {
    visibility: visible;
    opacity: 1;
    pointer-events: auto;
  }

  .document-search-overlay__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    min-block-size: 36px;
  }

  .document-search-overlay__header .catalog-summary {
    margin: 0;
  }

  .document-search-overlay__header button {
    min-block-size: 32px;
    padding: var(--space-1) var(--space-3);
    font-size: 12px;
  }

  .document-result-scroll {
    min-block-size: 0;
    overflow: auto;
    scrollbar-gutter: stable;
  }

  .document-search-columns {
    display: grid;
    min-block-size: 0;
  }

  .document-search-columns.selected-column {
    grid-template-columns: minmax(0, 1.1fr) minmax(360px, 0.9fr);
    gap: var(--space-2);
  }

  .document-result-card__body {
    align-self: stretch;
    align-items: center;
    cursor: default;
  }

  .document-search-overlay .catalog-card {
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

  .document-search-overlay .catalog-card + .catalog-card {
    margin-block-start: var(--space-2);
  }

  .document-search-overlay .catalog-card:hover {
    border-color: var(--line-strong);
    background: var(--surface-subtle);
  }

  .document-search-overlay .catalog-card__actions {
    display: grid;
    grid-template-rows: repeat(2, minmax(0, 1fr));
    gap: var(--space-2);
  }

  .document-search-overlay .catalog-card__actions > * {
    inline-size: 100%;
    min-block-size: 32px;
    padding: var(--space-1) var(--space-2);
    font-size: 11px;
  }

  .document-search-overlay .document-result-card__body {
    grid-template-columns: 44px minmax(0, 1fr);
    gap: var(--space-2);
  }

  .document-search-overlay .catalog-card img {
    inline-size: 44px;
    block-size: 44px;
  }

  .document-search-overlay .catalog-card__details > strong {
    font-size: 13px;
    line-height: 1.3;
  }

  .document-search-overlay .catalog-card__details > span {
    margin-block-start: 2px;
    font-size: 11px;
    line-height: 1.3;
  }

  .document-search-overlay .catalog-card__details > .catalog-card__price {
    margin-block-start: 3px;
    font-size: 14px;
  }

  .document-search-overlay .attribute-list {
    display: none;
  }

  .document-option-panel {
    display: grid;
    min-block-size: 0;
    grid-template-rows: auto minmax(0, 1fr);
    overflow: hidden;
    border: 1px solid var(--line);
    border-radius: var(--radius-control);
    background: var(--surface);
  }

  .document-option-panel__header {
    display: flex;
    min-inline-size: 0;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border-block-end: 1px solid var(--line);
    background: var(--surface-subtle);
  }

  .document-option-panel__header span,
  .document-option-panel__header h2 {
    display: block;
    margin: 0;
  }

  .document-option-panel__header span { color: var(--muted); font-size: 11px; }
  .document-option-panel__header h2 { overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
  .document-option-panel__header button { min-block-size: 32px; padding-inline: var(--space-2); font-size: 11px; }

  .document-option-groups { display: grid; min-block-size: 0; grid-template-rows: repeat(3, minmax(0, 1fr)); }
  .document-option-group { display: grid; min-block-size: 0; grid-template-rows: auto minmax(0, 1fr); }
  .document-option-group + .document-option-group { border-block-start: 1px solid var(--line); }
  .document-option-group h3 { margin: 0; padding: var(--space-2) var(--space-3); font-size: 12px; }
  .document-option-group h3 span { color: var(--muted); font-weight: 400; }
  .document-option-scroll { min-block-size: 0; overflow: auto; }
  .document-option-row { display: grid; grid-template-columns: 36px minmax(0, 1fr) 94px; align-items: center; gap: var(--space-2); min-block-size: 76px; padding: var(--space-2) var(--space-3); }
  .document-option-row + .document-option-row { border-block-start: 1px solid var(--line); }
  .document-option-row img { inline-size: 36px; block-size: 36px; object-fit: contain; background: var(--canvas); }
  .document-option-row > div:nth-child(2) { min-inline-size: 0; }
  .document-option-row strong, .document-option-row span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .document-option-row strong { font-size: 12px; }
  .document-option-row span { margin-block-start: 2px; color: var(--muted); font-size: 10px; }
  .document-option-row .option-row__price { color: var(--ink); font-size: 11px; font-weight: 700; }
  .document-option-row .catalog-card__actions { gap: var(--space-1); }
  .document-option-row .catalog-card__actions > * { min-block-size: 28px; padding: var(--space-1); font-size: 10px; }

  @media (min-width: 900px) {
    .document-catalog,
    .document-sheet {
      margin-block-start: 0;
    }

    .document-search-overlay {
      max-block-size: min(620px, calc(100dvh - 240px));
    }

    .document-table-wrap {
      max-block-size: min(720px, calc(100dvh - 300px));
    }
  }

  @media (max-width: 899px) {
    .document-search-columns.selected-column { grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(220px, 1fr) minmax(300px, 1fr); }
  }

  .document-sheet {
    border: 1px solid var(--line);
    background: var(--surface);
  }

  .document-table-wrap {
    max-block-size: calc(100dvh - 250px);
    overflow: auto;
    scrollbar-gutter: stable;
  }

  .document-table {
    min-inline-size: 2500px;
    border-collapse: separate;
    border-spacing: 0;
    table-layout: fixed;
  }

  .document-table th,
  .document-table td {
    padding: var(--space-3);
    border-inline-end: 1px solid var(--line);
    border-block-end: 1px solid var(--line);
    font-size: 13px;
    line-height: 1.45;
    overflow-wrap: anywhere;
    vertical-align: middle;
  }

  .document-table th {
    position: sticky;
    z-index: 2;
    color: var(--ink);
    background: var(--surface-selected);
    font-size: 12px;
    font-weight: 700;
    text-align: center;
  }

  /* Freeze only 연번 so the row stays identifiable while the remaining
     columns scroll horizontally. 품명 was sticky too but its fixed
     left offset broke the column width/wrap at narrow viewports. */
  .document-table tbody td:nth-child(1) {
    position: sticky;
    z-index: 1;
    inset-inline-start: 0;
    background: var(--surface);
    border-inline-end: 1px solid var(--line-strong);
    box-shadow: 6px 0 8px -8px color-mix(in srgb, var(--ink) 45%, transparent);
  }
  .document-table thead tr:first-child th:nth-child(1) {
    z-index: 3;
    inset-inline-start: 0;
  }

  .document-table thead tr:first-child th {
    inset-block-start: 0;
    block-size: 44px;
  }

  .document-table thead tr:nth-child(2) th {
    inset-block-start: 44px;
    block-size: 44px;
  }

  .document-table tbody tr {
    min-block-size: 84px;
  }

  .document-sequence {
    display: grid;
    justify-items: center;
    gap: var(--space-2);
    text-align: center;
  }

  .document-no-copy,
  .document-no-copy * {
    user-select: none;
  }

  .document-sequence button {
    min-block-size: 28px;
    padding: var(--space-1) var(--space-2);
    font-size: 11px;
  }

  .document-center {
    text-align: center;
  }

  .document-number {
    font-variant-numeric: tabular-nums;
    text-align: end;
    white-space: nowrap;
  }

  .document-baseline {
    background: var(--surface-subtle);
  }

  .document-product-link {
    color: var(--accent-dark);
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .document-product-link:hover,
  .document-product-link:focus-visible {
    color: var(--accent);
  }

  .spec-tooltip-trigger {
    display: block;
    inline-size: 100%;
    padding: 0;
    border: 0;
    border-radius: var(--radius-compact);
    color: inherit;
    background: transparent;
    font: inherit;
    text-align: inherit;
    cursor: help;
    outline: none;
  }

  .spec-tooltip-trigger:hover,
  .spec-tooltip-trigger:focus-visible {
    background: var(--focus);
  }

  .spec-tooltip {
    position: fixed;
    z-index: 30;
    inline-size: min(32rem, calc(100vw - var(--space-4)));
    max-block-size: min(20rem, calc(100dvh - var(--space-4)));
    overflow: auto;
    padding: var(--space-3);
    border: 1px solid var(--line);
    border-radius: var(--radius-control);
    color: var(--ink);
    background: var(--surface);
    box-shadow: 0 var(--space-2) var(--space-6) color-mix(in srgb, var(--ink) 14%, transparent);
    font-size: 13px;
    line-height: 1.55;
    pointer-events: none;
  }

  .spec-tooltip--above {
    transform: translateY(-100%);
  }

  .spec-tooltip p {
    margin: 0;
  }

  .spec-tooltip__title {
    margin-block-end: var(--space-2);
    color: var(--accent-dark);
  }

  .spec-tooltip dl {
    display: grid;
    gap: var(--space-2);
    margin: var(--space-3) 0 0;
    padding-block-start: var(--space-3);
    border-block-start: 1px solid var(--line);
  }

  .spec-tooltip dl div {
    display: grid;
    grid-template-columns: 92px minmax(0, 1fr);
    gap: var(--space-3);
  }

  .spec-tooltip dt {
    color: var(--muted);
  }

  .spec-tooltip dd {
    margin: 0;
  }

  .document-empty-row td {
    block-size: 72px;
  }

  .document-table .loading-placeholder {
    inline-size: 100%;
    margin-block: var(--space-1);
  }

  .col-sequence { inline-size: 70px; }
  .col-name { inline-size: 180px; }
  .col-spec { inline-size: 300px; }
  .col-unit { inline-size: 70px; }
  .col-price { inline-size: 120px; }
  .col-company { inline-size: 130px; }
  .col-company-spec { inline-size: 300px; }
  .col-id { inline-size: 130px; }
  .col-note { inline-size: 120px; }

  @media (max-width: 560px) {
    .document-catalog .catalog-controls {
      grid-template-columns: 1fr;
    }
  }
</style>
