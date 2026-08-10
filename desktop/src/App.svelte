<script lang="ts">
  import { onMount } from "svelte";

  import brandIcon from "../../KakaoTalk_20260804_113126254.png";
  import AppHeader from "./lib/components/AppHeader.svelte";
  import OfflineBanner from "./lib/components/OfflineBanner.svelte";
  import { listenForEstimateChanges, type EstimateChangeEvent, type EstimateChangeSubscriber } from "./lib/estimateEvents";
  import { desktopClient, type DesktopClient } from "./lib/invoke";
  import type { ConflictResolution, DesktopViewState, ReconciliationStatus } from "./lib/models";
  import { createLatestViewStateWriter, type DurableViewStateAdapter } from "./lib/viewState";
  import CatalogRoute from "./routes/CatalogRoute.svelte";
  import DataRoute from "./routes/DataRoute.svelte";
  import EstimateRoute from "./routes/EstimateRoute.svelte";
  import EstimatesRoute from "./routes/EstimatesRoute.svelte";

  type Route =
    | { name: "catalog"; path: "/" }
    | { name: "estimates"; path: "/estimates" }
    | { name: "estimate"; path: string; id: string }
    | { name: "data"; path: "/data" };

  let {
    client = desktopClient,
    initialPath = globalThis.location?.pathname ?? "/",
    subscribeEstimateChanges = listenForEstimateChanges,
  }: {
    client?: DesktopClient;
    initialPath?: string;
    subscribeEstimateChanges?: EstimateChangeSubscriber;
  } = $props();

  function matchRoute(pathname: string): Route {
    if (pathname === "/estimates") return { name: "estimates", path: "/estimates" };
    if (pathname === "/data") return { name: "data", path: "/data" };
    const match = pathname.match(/^\/estimates\/([^/]+)$/);
    if (match) {
      try {
        const id = decodeURIComponent(match[1]);
        if (id) return { name: "estimate", path: pathname, id };
      } catch {
        // Malformed deep links safely return to the catalog.
      }
    }
    return { name: "catalog", path: "/" };
  }

  let route = $state<Route>(matchRoute("/"));
  let reconciliation = $state<ReconciliationStatus | null>(null);
  let reconciliationBusy = $state(false);
  let estimateChange = $state<EstimateChangeEvent | null>(null);
  let estimateChangeVersion = $state(0);
  let viewRestored = false;
  let routeEdited = false;
  const viewAdapter: DurableViewStateAdapter = {
    load: () => client.loadDesktopView(),
    save: (state) => client.saveDesktopView(state),
  };
  const writeLatestView = createLatestViewStateWriter(viewAdapter);
  const active = $derived(route.name === "estimate" ? "estimates" : route.name);
  const pageTitle = $derived(route.name === "catalog" ? "물품 검색" : route.name === "data" ? "데이터 상태" : "문서 작성");
  const showReconciliation = $derived(Boolean(
    reconciliation
      && (!reconciliation.online
        || reconciliation.state !== "idle"
        || reconciliation.queued_count > 0
        || reconciliation.conflicts.length > 0),
  ));

  function viewState(value: Route): DesktopViewState {
    return { route: value.name, path: value.path };
  }

  function navigate(path: string) {
    const next = matchRoute(path);
    routeEdited = true;
    route = next;
    if (viewRestored) void writeLatestView(viewState(next));
    if (globalThis.history && globalThis.location?.pathname !== next.path) {
      globalThis.history.pushState({}, "", next.path);
    }
    queueMicrotask(() => globalThis.document?.getElementById("main")?.focus());
  }

  function navigateHeader(next: "catalog" | "estimates" | "data") {
    navigate(next === "catalog" ? "/" : `/${next}`);
  }

  async function restoreView() {
    if (typeof client.loadDesktopView !== "function") {
      viewRestored = true;
      return;
    }
    try {
      const saved = await viewAdapter.load();
      if (initialPath === "/" && !routeEdited && saved?.path) {
        route = matchRoute(saved.path);
      }
    } catch {
      // A missing or unreadable durable view is equivalent to first launch.
    } finally {
      viewRestored = true;
      void writeLatestView(viewState(route));
    }
  }

  async function refreshReconciliation() {
    if (typeof client.getReconciliationStatus !== "function") return;
    try {
      reconciliation = await client.getReconciliationStatus();
    } catch {
      if (globalThis.navigator && !globalThis.navigator.onLine) {
        reconciliation = {
          state: "offline",
          online: false,
          queued_count: reconciliation?.queued_count ?? 0,
          conflicts: reconciliation?.conflicts ?? [],
        };
      }
    }
  }

  async function retryReconciliation() {
    if (reconciliationBusy || typeof client.replayPendingChanges !== "function") return;
    reconciliationBusy = true;
    if (reconciliation) reconciliation = { ...reconciliation, state: "replaying" };
    try {
      reconciliation = await client.replayPendingChanges();
    } catch {
      reconciliation = {
        state: "offline",
        online: false,
        queued_count: reconciliation?.queued_count ?? 0,
        conflicts: reconciliation?.conflicts ?? [],
      };
    } finally {
      reconciliationBusy = false;
    }
  }

  async function resolveConflict(sequence: number, resolution: ConflictResolution) {
    if (reconciliationBusy || typeof client.resolveReconciliationConflict !== "function") return;
    reconciliationBusy = true;
    try {
      reconciliation = await client.resolveReconciliationConflict({ sequence, resolution });
    } finally {
      reconciliationBusy = false;
    }
  }

  $effect(() => {
    route = matchRoute(initialPath);
  });

  onMount(() => {
    let listenerDisposed = false;
    let unlistenEstimateChanges: (() => void) | undefined;
    void subscribeEstimateChanges((change) => {
      if (listenerDisposed) return;
      estimateChange = change;
      estimateChangeVersion += 1;
    }).then((unlisten) => {
      if (listenerDisposed) {
        unlisten();
      } else {
        unlistenEstimateChanges = unlisten;
      }
    }).catch(() => {
      // The command surface remains usable when the native event bridge is unavailable.
    });

    const popstate = () => {
      routeEdited = true;
      route = matchRoute(globalThis.location.pathname);
      if (viewRestored) void writeLatestView(viewState(route));
    };
    const offline = () => {
      reconciliation = {
        state: "offline",
        online: false,
        queued_count: reconciliation?.queued_count ?? 0,
        conflicts: reconciliation?.conflicts ?? [],
      };
    };
    const online = () => void refreshReconciliation();
    globalThis.addEventListener("popstate", popstate);
    globalThis.addEventListener("offline", offline);
    globalThis.addEventListener("online", online);
    void restoreView();
    void refreshReconciliation();
    return () => {
      listenerDisposed = true;
      unlistenEstimateChanges?.();
      globalThis.removeEventListener("popstate", popstate);
      globalThis.removeEventListener("offline", offline);
      globalThis.removeEventListener("online", online);
    };
  });
</script>

<svelte:head>
  <title>{pageTitle} | G2B Compare</title>
  <meta name="description" content="G2B product comparison workspace" />
  <link rel="icon" type="image/png" href={brandIcon} />
</svelte:head>

<div class:shell--reconciliation={showReconciliation} class="shell">
  <a class="skip-link" href="#main">본문으로 건너뛰기</a>
  <AppHeader {active} onNavigate={navigateHeader} />
  {#if reconciliation && showReconciliation}
    <OfflineBanner status={reconciliation} busy={reconciliationBusy} onRetry={() => void retryReconciliation()} onResolve={(sequence, resolution) => void resolveConflict(sequence, resolution)} />
  {/if}
  <p class="visually-hidden">로컬 데스크톱 앱 준비 중</p>
  <main id="main" class="shell__body" tabindex="-1">
    <div class="content" data-route={route.name}>
      {#if route.name === "catalog"}
        <CatalogRoute {client} />
      {:else if route.name === "estimates"}
        <EstimatesRoute
          {client}
          onNavigate={navigate}
          onReconciliation={() => void refreshReconciliation()}
          externalChange={estimateChange}
          {estimateChangeVersion}
        />
      {:else if route.name === "estimate"}
        <EstimateRoute
          id={route.id}
          {client}
          onNavigate={navigate}
          onReconciliation={() => void refreshReconciliation()}
          externalChange={estimateChange}
          {estimateChangeVersion}
        />
      {:else}
        <DataRoute {client} onReconciliation={() => void refreshReconciliation()} />
      {/if}
    </div>
  </main>
</div>
