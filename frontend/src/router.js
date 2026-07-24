const CORE_ROUTES = new Set(["/", "/estimates", "/data"]);

export function restoredSearch(currentSearch, searchEdited, state) {
  return !searchEdited && typeof state?.search === "string"
    ? state.search
    : currentSearch;
}

export function createLatestStateWriter(write) {
  let pending;
  let hasPending = false;
  let running = null;

  function pump() {
    running = (async () => {
      while (hasPending) {
        const value = pending;
        hasPending = false;
        try {
          await write(value);
        } catch {
          // Persistence failure must not block a later local edit.
        }
      }
    })().finally(() => {
      running = null;
      if (hasPending) pump();
    });
  }

  return (value) => {
    pending = value;
    hasPending = true;
    if (running === null) pump();
    return running;
  };
}

export function matchRoute(pathname) {
  if (pathname === "/") return { name: "catalog", path: "/" };
  if (pathname === "/estimates") {
    return { name: "estimates", path: "/estimates" };
  }
  if (pathname === "/data") return { name: "data", path: "/data" };

  const match = pathname.match(/^\/estimates\/([^/]+)$/);
  if (match === null) return null;
  try {
    const id = decodeURIComponent(match[1]);
    if (id.length === 0) return null;
    return { name: "estimate", path: pathname, params: { id } };
  } catch {
    return null;
  }
}

export function isCorePath(pathname) {
  return CORE_ROUTES.has(pathname) || matchRoute(pathname)?.name === "estimate";
}

export function shouldHandleNavigation(event, anchor, windowObject = window) {
  if (
    event.defaultPrevented ||
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey ||
    anchor.target ||
    !("spaLink" in anchor.dataset)
  ) {
    return false;
  }
  const url = new URL(anchor.href, windowObject.location.origin);
  return url.origin === windowObject.location.origin && isCorePath(url.pathname);
}

export function createRouter(onRoute, windowObject = window) {
  const emitCurrent = () => onRoute(matchRoute(windowObject.location.pathname));
  windowObject.addEventListener("popstate", emitCurrent);
  emitCurrent();

  return {
    navigate(href, { replace = false } = {}) {
      const url = new URL(href, windowObject.location.origin);
      if (url.origin !== windowObject.location.origin || !isCorePath(url.pathname)) {
        return false;
      }
      const method = replace ? "replaceState" : "pushState";
      windowObject.history[method]({}, "", `${url.pathname}${url.search}${url.hash}`);
      emitCurrent();
      return true;
    },
    destroy() {
      windowObject.removeEventListener("popstate", emitCurrent);
    },
  };
}
