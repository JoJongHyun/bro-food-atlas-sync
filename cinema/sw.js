// BRO CINEMA PWA shell. Network-first navigation; no TVWiki/video/API caching.
const SHELL_CACHE = "bro-cinema-shell-v1";
const SHELL_URL = new URL("./", self.registration.scope).toString();
self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(SHELL_CACHE)
      .then(cache => cache.addAll([SHELL_URL]))
      .then(() => self.skipWaiting())
  );
});
self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k.startsWith("bro-cinema-shell-") && k !== SHELL_CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});
self.addEventListener("fetch", event => {
  const req = event.request;
  if (req.mode !== "navigate" || new URL(req.url).origin !== self.location.origin) return;
  event.respondWith(
    fetch(req).then(response => {
      if (response.ok) {
        const copy = response.clone();
        event.waitUntil(caches.open(SHELL_CACHE).then(cache => cache.put(SHELL_URL, copy)));
      }
      return response;
    }).catch(() => caches.match(SHELL_URL))
  );
});
