/*
 * Parda service worker: keeps the app shell and its build assets available without a connection.
 *
 * What it never touches: /api (personal data stays out of the browser cache; saved tickets are kept by the app
 * itself and wiped on sign-out), non-GET requests, and other origins (film posters). Pages are network-first so an
 * online visitor always gets the newest build; build assets are hashed and immutable, so they are cache-first.
 */
const SHELL_CACHE = 'parda-shell-v1'
const ASSET_CACHE = 'parda-assets-v1'
const ASSET_LIMIT = 80
const STATIC_FILES = ['/manifest.webmanifest', '/parda-logo-mark.jpg', '/icon-192.png', '/icon-512.png', '/icon-maskable-512.png', '/apple-touch-icon.png']

function routeFor(request, url, origin) {
  if (request.method !== 'GET' || url.origin !== origin) return 'bypass'
  if (url.pathname.startsWith('/api/') || url.pathname === '/health' || url.pathname === '/sw.js') return 'bypass'
  if (request.mode === 'navigate') return 'shell'
  if (url.pathname.startsWith('/assets/')) return 'asset'
  if (STATIC_FILES.includes(url.pathname)) return 'asset'
  return 'bypass'
}

async function trim(cache, limit) {
  const keys = await cache.keys()
  for (const key of keys.slice(0, Math.max(0, keys.length - limit))) await cache.delete(key)
}

async function shellResponse(request) {
  const cache = await caches.open(SHELL_CACHE)
  try {
    const fresh = await fetch(request)
    const type = fresh.headers.get('Content-Type') || ''
    if (fresh.status === 200 && type.includes('text/html')) await cache.put('/', fresh.clone())
    return fresh
  } catch (error) {
    const saved = await cache.match('/')
    if (saved) return saved
    return new Response('<!doctype html><meta charset="utf-8"><title>Parda</title><p>Internet aloqasi yo‘q. Qayta urinib ko‘ring.</p>',
      { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } })
  }
}

async function assetResponse(request) {
  const cache = await caches.open(ASSET_CACHE)
  const saved = await cache.match(request)
  if (saved) return saved
  const fresh = await fetch(request)
  if (fresh.status === 200 && fresh.type !== 'opaque') {
    await cache.put(request, fresh.clone())
    await trim(cache, ASSET_LIMIT)
  }
  return fresh
}

self.addEventListener('install', event => {
  event.waitUntil(caches.open(SHELL_CACHE).then(cache => cache.add('/')).then(() => self.skipWaiting()))
})

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(names => Promise.all(names.filter(name => ![SHELL_CACHE, ASSET_CACHE].includes(name)).map(name => caches.delete(name))))
      .then(() => self.clients.claim()))
})

self.addEventListener('fetch', event => {
  const route = routeFor(event.request, new URL(event.request.url), self.location.origin)
  if (route === 'shell') event.respondWith(shellResponse(event.request))
  else if (route === 'asset') event.respondWith(assetResponse(event.request))
})
