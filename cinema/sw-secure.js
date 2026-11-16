// BRO CINEMA access-controlled edition: never cache protected pages or catalog.
self.addEventListener('install', event => event.waitUntil(self.skipWaiting()));
self.addEventListener('activate', event => event.waitUntil(
  caches.keys().then(keys => Promise.all(keys.map(key => caches.delete(key))))
    .then(() => self.clients.claim())
));
self.addEventListener('fetch', event => {
  const request = event.request;
  if (new URL(request.url).origin !== self.location.origin) return;
  if (request.method === 'GET') {
    event.respondWith(fetch(request, {cache:'no-store'}));
  }
});
