// Jarvis : l'interface s'ouvre même quand le PC est éteint (mode autonome du téléphone)
const CACHE = "jarvis-v5";
const SHELL = ["/", "/static/hud.css", "/static/hud.js", "/static/fx.js", "/static/hands.js", "/static/manifest.json",
  "/static/icon.svg", "/static/fonts/orbitron-latin-500-normal.woff2", "/static/fonts/orbitron-latin-700-normal.woff2",
  "/static/fonts/orbitron-latin-900-normal.woff2", "/static/fonts/rajdhani-latin-500-normal.woff2",
  "/static/fonts/rajdhani-latin-600-normal.woff2", "/static/fonts/rajdhani-latin-700-normal.woff2"];
self.addEventListener("install", (e) => { e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {})); self.skipWaiting(); });
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin || u.pathname.startsWith("/api/")) return;
  // réseau d'abord (toujours la dernière version), cache si le PC ne répond pas
  e.respondWith(fetch(e.request).then((r) => {
    const copy = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); return r;
  }).catch(() => caches.match(e.request, { ignoreSearch: true })));
});
