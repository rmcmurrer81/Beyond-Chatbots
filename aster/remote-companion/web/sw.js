'use strict';
// No background sync, microphone, push subscription, or caching of private API data.
const CACHE = 'aster-shell-v1';
const ASSETS = ['/', '/app.js', '/style.css', '/icon.svg', '/manifest.webmanifest'];
self.addEventListener('install', event => event.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS))));
self.addEventListener('activate', event => event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k.startsWith('aster-shell-') && k !== CACHE).map(k => caches.delete(k))))));
self.addEventListener('fetch', event => {
  const u = new URL(event.request.url);
  if (event.request.method !== 'GET' || u.origin !== self.location.origin || !ASSETS.includes(u.pathname) || u.search) return;
  event.respondWith(fetch(event.request).catch(() => caches.match(event.request)));
});
