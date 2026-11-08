// Wander's service worker. Two jobs:
// 1. Receive Android shares (Web Share Target, POST /share-target): store them in the IndexedDB
//    outbox and answer at once, so sharing works offline and even with an expired login.
// 2. Keep the app shell available offline (network first, cached copy as a fallback).
// The page (src/queue.ts) sends the outbox to /api/capture. Keep DB/STORE in sync with it.
const DB = "wander";
const STORE = "outbox";
const SHELL = "wander-shell-v1";

function openDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: "id", autoIncrement: true });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function store(item) {
  const db = await openDb();
  await new Promise((resolve, reject) => {
    const t = db.transaction(STORE, "readwrite");
    t.objectStore(STORE).add(item);
    t.oncomplete = resolve;
    t.onerror = () => reject(t.error);
  });
}

async function receiveShare(request) {
  const form = await request.formData();
  const parts = [form.get("title"), form.get("text"), form.get("url")].filter((v) => typeof v === "string" && v.trim());
  // Many apps repeat the link in "text"; keep each distinct piece once.
  const text = [...new Set(parts.map((p) => p.trim()))].join("\n");
  const files = form.getAll("media").filter((f) => f instanceof File && f.size > 0);
  await store({ text, files, source_app: "share-target", at: Date.now() });
  return Response.redirect("/#/capture?shared=1", 303);
}

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== location.origin) return;
  if (event.request.method === "POST" && url.pathname === "/share-target") {
    event.respondWith(receiveShare(event.request));
    return;
  }
  if (event.request.method !== "GET" || url.pathname.startsWith("/api/")) return;
  event.respondWith(
    fetch(event.request)
      .then((res) => {
        // Only cache real app files, never Access's login redirects.
        if (res.ok && !res.redirected && res.type === "basic") {
          const copy = res.clone();
          caches.open(SHELL).then((c) => c.put(event.request, copy));
        }
        return res;
      })
      .catch(async () => (await caches.match(event.request)) || (await caches.match("/")) || Response.error()),
  );
});
