const CACHE = "diavgeia-v1";
const SHELL = ["/", "/index.html", "/manifest.json", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);

  // Τα δεδομένα ΠΟΤΕ δεν αποθηκεύονται — μόνο το κέλυφος.
  if (url.pathname === "/ask" || url.pathname === "/stats") return;
  if (e.request.method !== "GET") return;

  e.respondWith(caches.match(e.request).then(hit => hit || fetch(e.request)));
});