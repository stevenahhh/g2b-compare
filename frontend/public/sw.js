const CACHE_NAME = 'g2b-spa-shell-v1';
const CORE_ROUTES = new Set(['/', '/estimates', '/data']);

function isCoreRoute(pathname) {
  return CORE_ROUTES.has(pathname) || /^\/estimates\/[^/]+$/.test(pathname);
}

function isBuildAsset(url) {
  return url.origin === self.location.origin && url.pathname.startsWith('/assets/');
}

function bootAssets(index) {
  return Array.from(
    index.matchAll(/(?:src|href)=["']([^"']+)["']/g),
    (match) => new URL(match[1], self.location.origin),
  )
    .filter(isBuildAsset)
    .map((url) => url.pathname);
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    fetch('/').then(async (response) => {
      if (!response.ok) {
        throw new Error(`Unable to cache application shell: ${response.status}`);
      }
      const index = await response.text();
      const cache = await caches.open(CACHE_NAME);
      await cache.addAll(['/', ...bootAssets(index)]);
    }),
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') {
    return;
  }

  const url = new URL(request.url);
  if (request.mode === 'navigate' && isCoreRoute(url.pathname)) {
    event.respondWith(
      fetch(request).catch(() => caches.match('/'))
    );
    return;
  }

  if (!isBuildAsset(url)) {
    return;
  }

  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) {
        return cached;
      }
      return fetch(request).then((response) => {
        if (!response.ok) {
          return response;
        }
        const cachedResponse = response.clone();
        return caches
          .open(CACHE_NAME)
          .then((cache) => cache.put(request, cachedResponse))
          .then(() => response);
      });
    })
  );
});
