/**
 * Offline shell: only same-origin, build-listed application assets are cached.
 * User-provided saves use the File API/Worker in memory and are never cached.
 * The build substitutes a content-derived cache version and exact asset list.
 */
const CACHE_NAME = __ATLAS_CACHE_NAME__;
const ASSETS = __ATLAS_ASSETS__;
const ALLOWED_PATHS = new Set(ASSETS.map((path) =>
  new URL(path, self.registration.scope).pathname));

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(ASSETS))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((key) =>
      key.startsWith("sm-atlas-shell-") && key !== CACHE_NAME)
      .map((key) => caches.delete(key)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin
      || !ALLOWED_PATHS.has(url.pathname)) return;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE_NAME);
    const cached = await cache.match(request, { ignoreSearch: true });
    // Cached app shell works offline. Unknown paths, including any save
    // endpoint, are never intercepted or persisted by this worker.
    return cached || fetch(request);
  })());
});
