const CACHE = 'baizora-v1';

const APP_SHELL = [
  '/',
  '/index.html',
  '/index_cn.html',
  '/firebase.js',
  '/assets/baize_favicon_v2.png',
  '/assets/baize_logo_v2.png',
  '/assets/icon-192.png',
  '/assets/icon-512.png'
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(APP_SHELL))
  );
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // Always fetch fresh for scanner data and Firebase/Stripe
  if (
    url.pathname.includes('latest.json') ||
    url.hostname.includes('firebase') ||
    url.hostname.includes('stripe') ||
    url.hostname.includes('cloudfunctions')
  ) {
    e.respondWith(fetch(e.request));
    return;
  }

  // Cache-first for everything else (app shell, assets, fonts)
  e.respondWith(
    caches.match(e.request).then(cached => {
      if (cached) return cached;
      return fetch(e.request).then(res => {
        if (res.ok) {
          const clone = res.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return res;
      });
    }).catch(() => caches.match('/index.html'))
  );
});
