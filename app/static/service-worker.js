const CACHE = "mac-image-lab-shell-v1";
const SHELL = [
  "/static/style.css",
  "/static/workspace.js",
  "/static/manifest.webmanifest",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png"
];

self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});

self.addEventListener("fetch", event => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;

  // Private images, runs, APIs, exports, and navigations are never cached.
  if (!SHELL.includes(url.pathname)) {
    if (event.request.mode === "navigate") {
      event.respondWith(fetch(event.request).catch(() => new Response(
        "<!doctype html><meta name='viewport' content='width=device-width'><title>Image Lab offline</title><style>body{font:18px system-ui;margin:3rem;max-width:42rem;background:#f4efe7;color:#1f2824}a{color:inherit}</style><h1>Image Lab is unreachable</h1><p>Your unsent text remains on this device. Reconnect Tailscale or the host Mac, then reload.</p><p><a href='/'>Try again</a></p>",
        {status: 503, headers: {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}}
      )));
    }
    return;
  }

  event.respondWith(fetch(event.request).then(response => {
    if (response.ok) {
      const copy = response.clone();
      event.waitUntil(caches.open(CACHE).then(cache => cache.put(event.request, copy)));
    }
    return response;
  }).catch(() => caches.match(event.request)));
});
