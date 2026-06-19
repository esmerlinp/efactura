const CACHE_NAME = 'efactura-static-v1';

const PRECACHE_URLS = [
  '/static/css/style_moderno.css',
  '/static/css/style_clasico.css',
  '/static/css/style_landing.css',
  '/static/js/main.js',
  '/static/js/invoicing.js',
  '/static/js/client_crm.js',
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(PRECACHE_URLS);
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  const validCaches = [CACHE_NAME];
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.filter(key => !validCaches.includes(key))
          .map(key => caches.delete(key))
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // Only cache GET requests to our own static files
  if (
    request.method !== 'GET' ||
    url.origin !== location.origin ||
    !url.pathname.startsWith('/static/')
  ) {
    return;
  }

  event.respondWith(
    caches.match(request).then(cached => {
      const fetchPromise = fetch(request).then(networkResponse => {
        if (networkResponse && networkResponse.ok) {
          const responseClone = networkResponse.clone();
          caches.open(CACHE_NAME).then(cache => {
            cache.put(request, responseClone);
          });
        }
        return networkResponse;
      }).catch(() => cached);

      return cached || fetchPromise;
    })
  );
});
