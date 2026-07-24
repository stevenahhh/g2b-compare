<script>
  import { onMount } from "svelte";

  import Modal from "./components/Modal.svelte";
  import OfflineBanner from "./components/OfflineBanner.svelte";
  import { requestJson } from "./api.js";
  import { getAppState, putAppState } from "./lib/db.js";
  import { syncPendingEstimates } from "./lib/sync.js";
  import { createLatestStateWriter, matchRoute, restoredSearch } from "./router.js";
  import CatalogRoute from "./routes/CatalogRoute.svelte";
  import DataRoute from "./routes/DataRoute.svelte";
  import EstimateRoute from "./routes/EstimateRoute.svelte";
  import EstimatesRoute from "./routes/EstimatesRoute.svelte";

  const STATE_KEY = "shell";
  const initialRoute = matchRoute(window.location.pathname);
  const openedFromLegacyPath = window.location.pathname !== "/";
  let view = $state(initialRoute?.name ?? "estimates");
  let estimateId = $state(initialRoute?.params?.id ?? null);
  let restoring = true;
  let searchEdited = false;
  let search = $state("");
  let offline = $state(!navigator.onLine);
  let modal = $state(null);
  let estimateRevision = $state(0);
  const writeState = createLatestStateWriter((state) => putAppState(STATE_KEY, state));
  const pageTitle = $derived(view === "catalog" ? "검색" : view === "estimates" ? "문서 작성" : view === "estimate" ? "문서 작성" : "데이터");

  function saveState() {
    if (!restoring) void writeState({ search, view, estimateId });
  }
  function showView(nextView, nextEstimateId = null) {
    view = nextView;
    estimateId = nextEstimateId;
    if (window.location.pathname !== "/") window.history.replaceState({}, "", "/");
    saveState();
    requestAnimationFrame(() => document.querySelector("#main")?.focus());
  }
  function navigate(path) {
    const route = matchRoute(new URL(path, window.location.origin).pathname);
    if (!route) return;
    showView(route.name, route.params?.id ?? null);
  }
  function updateSearch(value) { searchEdited = true; search = value; saveState(); }
  function reportCoreFailure(error) {
    offline = Boolean(error?.offline) || !navigator.onLine;
    void runSync();
  }
  function closeModal() { modal = null; }
  function estimateChanged() { estimateRevision += 1; }
  async function retrySync() {
    modal = null;
    try {
      await syncPendingEstimates(globalThis.fetch, estimateChanged);
      await requestJson("/healthz");
      offline = false;
    } catch {
      offline = true;
    }
  }
  async function runSync() {
    try {
      await syncPendingEstimates(globalThis.fetch, estimateChanged);
    } catch {
      offline = true;
    }
  }
  function confirmRetry() {
    modal = { kind: "confirm", title: "서버 연결 다시 확인", message: "저장 대기 중인 문서를 다시 전송할까요?", confirmLabel: "다시 시도", action: retrySync };
  }
  async function runModalAction() { await modal?.action?.(); }

  onMount(() => {
    document.documentElement.removeAttribute("data-theme");
    try { localStorage.removeItem("g2b-theme"); } catch {}
    window.history.replaceState({}, "", "/");
    const setOnline = () => { offline = false; void runSync(); };
    const setOffline = () => { offline = true; };
    const estimateEvents = new EventSource("/api/estimates/events");
    estimateEvents.addEventListener("estimate-saved", estimateChanged);
    estimateEvents.addEventListener("estimate-deleted", estimateChanged);
    window.addEventListener("online", setOnline);
    window.addEventListener("offline", setOffline);
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(reportCoreFailure);
    void runSync();
    void getAppState(STATE_KEY).then((state) => {
      search = restoredSearch(search, searchEdited, state);
      if (!openedFromLegacyPath && ["catalog", "estimates", "estimate", "data"].includes(state?.view)) {
        view = state.view;
        estimateId = state.estimateId ?? null;
        if (view === "estimate" && !estimateId) view = "estimates";
      }
    }).catch(() => {}).finally(() => { restoring = false; saveState(); });
    return () => { estimateEvents.close(); window.removeEventListener("online", setOnline); window.removeEventListener("offline", setOffline); };
  });
</script>

<svelte:head><title>{pageTitle} | G2B Compare</title><meta name="description" content="G2B product comparison workspace" /><link rel="icon" href="data:," /></svelte:head>

<div class="shell">
  <a class="skip-link" href="#main">본문으로 건너뛰기</a>
  <header class="app-header">
    <nav class="app-nav" aria-label="주요 메뉴">
      <button class="home-link" type="button" aria-label="홈" title="홈" onclick={() => showView("catalog")}>
        <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m4 11 8-7 8 7"></path><path d="M6 10v10h12V10M10 20v-6h4v6"></path></svg>
      </button>
      <button type="button" aria-current={view === "estimates" || view === "estimate" ? "page" : undefined} onclick={() => showView("estimates")}>문서 작성</button>
      <button type="button" aria-current={view === "catalog" ? "page" : undefined} onclick={() => showView("catalog")}>물품 검색</button>
      <button type="button" aria-current={view === "data" ? "page" : undefined} onclick={() => showView("data")}>데이터 상태</button>
    </nav>
  </header>
  {#if offline}<OfflineBanner onRetry={confirmRetry} />{/if}
  <main id="main" class="shell__body" tabindex="-1"><div class="content" data-route={view}>
    {#if view === "catalog"}<CatalogRoute {search} onSearch={updateSearch} onFailure={reportCoreFailure} onSynced={estimateChanged} />
    {:else if view === "estimates"}<EstimatesRoute revision={estimateRevision} onNavigate={navigate} onFailure={reportCoreFailure} />
    {:else if view === "estimate" && estimateId}<EstimateRoute id={estimateId} onNavigate={navigate} onFailure={reportCoreFailure} onSynced={estimateChanged} />
    {:else if view === "data"}<DataRoute onFailure={reportCoreFailure} />{/if}
  </div></main>
</div>
{#if modal}<Modal open kind={modal.kind} title={modal.title} message={modal.message} confirmLabel={modal.confirmLabel} onConfirm={runModalAction} onCancel={closeModal} />{/if}
