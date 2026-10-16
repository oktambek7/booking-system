/**
 * Runs the real public/sw.js in a sandbox with an in-memory Cache Storage and a scripted network, and checks what it
 * caches, what it refuses to cache, and what it serves when the network is gone.
 */
import { describe, expect, it } from 'vitest'
import SOURCE from '../public/sw.js?raw'
const ORIGIN = 'https://phantora.example'

class FakeCache {
  entries = new Map<string, Response>()
  private key = (request: Request | string) => (typeof request === 'string' ? new URL(request, ORIGIN).href : request.url)
  async put(request: Request | string, response: Response) { this.entries.set(this.key(request), response) }
  async match(request: Request | string) { return this.entries.get(this.key(request))?.clone() }
  async add(request: string) { this.entries.set(this.key(request), await sandboxFetch(new Request(new URL(request, ORIGIN)))) }
  async keys() { return [...this.entries.keys()].map(url => new Request(url)) }
  async delete(request: Request | string) { return this.entries.delete(this.key(request)) }
}

let network: (request: Request) => Promise<Response> | Response
let sandboxFetch: (request: Request) => Promise<Response>

function boot() {
  const caches = new Map<string, FakeCache>()
  const listeners: Record<string, (event: unknown) => void> = {}
  const calls = { skipWaiting: 0, claim: 0 }
  sandboxFetch = async (request: Request) => network(request)
  const self = {
    location: { origin: ORIGIN },
    addEventListener: (type: string, listener: (event: unknown) => void) => { listeners[type] = listener },
    skipWaiting: () => { calls.skipWaiting += 1; return Promise.resolve() },
    clients: { claim: () => { calls.claim += 1; return Promise.resolve() } },
  }
  const cacheStorage = {
    open: async (name: string) => { if (!caches.has(name)) caches.set(name, new FakeCache()); return caches.get(name)! },
    keys: async () => [...caches.keys()],
    delete: async (name: string) => caches.delete(name),
  }
  new Function('self', 'caches', 'fetch', 'Response', 'Request', 'URL', 'Math', 'Promise', SOURCE)(self, cacheStorage, (request: Request) => sandboxFetch(request), Response, Request, URL, Math, Promise)
  const event = async (type: string, request?: Request) => {
    let answer: Promise<Response> | undefined
    let work: Promise<unknown> | undefined
    listeners[type]({ request, respondWith: (p: Promise<Response>) => { answer = p }, waitUntil: (p: Promise<unknown>) => { work = p } })
    await work
    return answer ? await answer : undefined
  }
  return { caches, calls, event, handled: (request: Request) => { let handled = false; listeners.fetch({ request, respondWith: () => { handled = true } }); return handled } }
}

const html = (body = '<html>shell</html>') => new Response(body, { status: 200, headers: { 'Content-Type': 'text/html' } })
const navigate = (path = '/') => Object.defineProperty(new Request(ORIGIN + path), 'mode', { value: 'navigate' })
const get = (path: string) => new Request(ORIGIN + path)

describe('service worker', () => {
  it('stores the app shell when installed and takes over immediately', async () => {
    network = () => html()
    const sw = boot()
    await sw.event('install')
    expect(await (await sw.caches.get('phantora-shell-v1')!.match('/'))!.text()).toBe('<html>shell</html>')
    expect(sw.calls.skipWaiting).toBe(1)
    await sw.event('activate')
    expect(sw.calls.claim).toBe(1)
  })

  it('serves the newest page when online and refreshes the saved copy', async () => {
    network = () => html('<html>v1</html>')
    const sw = boot()
    await sw.event('install')
    network = () => html('<html>v2</html>')
    expect(await (await sw.event('fetch', navigate('/some/deep/link')))!.text()).toBe('<html>v2</html>')
    expect(await (await sw.caches.get('phantora-shell-v1')!.match('/'))!.text()).toBe('<html>v2</html>')
  })

  it('falls back to the saved page for any address when the network is gone', async () => {
    network = () => html('<html>saved</html>')
    const sw = boot()
    await sw.event('install')
    network = () => { throw new TypeError('Failed to fetch') }
    expect(await (await sw.event('fetch', navigate('/?panel=bookings')))!.text()).toBe('<html>saved</html>')
  })

  it('shows a plain offline message when nothing was ever saved', async () => {
    network = () => { throw new TypeError('Failed to fetch') }
    const sw = boot()
    const response = (await sw.event('fetch', navigate()))!
    expect(response.status).toBe(503)
    expect(await response.text()).toContain('Internet aloqasi yo')
  })

  it('does not save an error page as the shell', async () => {
    network = () => html()
    const sw = boot()
    await sw.event('install')
    network = () => new Response('<html>down</html>', { status: 502, headers: { 'Content-Type': 'text/html' } })
    await sw.event('fetch', navigate())
    network = () => { throw new TypeError('offline') }
    expect(await (await sw.event('fetch', navigate()))!.text()).toBe('<html>shell</html>')
  })

  it('caches build assets once and serves them without the network', async () => {
    let hits = 0
    network = () => { hits += 1; return new Response('console.log(1)', { status: 200 }) }
    const sw = boot()
    await sw.event('fetch', get('/assets/index-abc123.js'))
    network = () => { throw new TypeError('offline') }
    expect(await (await sw.event('fetch', get('/assets/index-abc123.js')))!.text()).toBe('console.log(1)')
    expect(hits).toBe(1)
  })

  it('never touches the API, writes, other origins or the worker itself', () => {
    network = () => html()
    const sw = boot()
    for (const request of [get('/api/bookings'), get('/api/auth/me'), get('/health'), get('/sw.js'),
      new Request(ORIGIN + '/api/bookings', { method: 'POST', body: '{}' }), new Request('https://cinematica.uz/poster.jpg'),
      get('/some-random-file.txt')]) {
      expect(sw.handled(request), request.url).toBe(false)
    }
  })

  it('does not answer an API address opened as a page with the cached app shell', async () => {
    network = () => html()
    const sw = boot()
    await sw.event('install')
    for (const path of ['/api/docs', '/api/account/export', '/health', '/sw.js']) {
      expect(sw.handled(navigate(path)), path).toBe(false)
    }
  })

  it('ignores assets served by another origin even when the path looks like ours', () => {
    network = () => html()
    const sw = boot()
    for (const url of ['https://cdn.example/assets/app.js', 'https://cinematica.uz/assets/logo.png']) {
      expect(sw.handled(new Request(url)), url).toBe(false)
    }
  })

  it('never stores API responses, even for requests that carry credentials', async () => {
    network = () => new Response('{"secret":true}', { status: 200 })
    const sw = boot()
    await sw.event('install')
    sw.handled(new Request(ORIGIN + '/api/account/export', { headers: { Authorization: 'Bearer x' } }))
    for (const cache of sw.caches.values()) {
      for (const url of cache.entries.keys()) expect(url).not.toContain('/api/')
    }
  })

  it('keeps the asset cache bounded', async () => {
    network = () => new Response('x', { status: 200 })
    const sw = boot()
    for (let i = 0; i < 95; i += 1) await sw.event('fetch', get(`/assets/chunk-${i}.js`))
    expect(sw.caches.get('phantora-assets-v1')!.entries.size).toBe(80)
  })

  it('deletes caches left by an older version when activated', async () => {
    network = () => html()
    const sw = boot()
    await sw.caches.set('phantora-shell-v0', new FakeCache())
    await sw.event('install')
    await sw.event('activate')
    expect([...sw.caches.keys()].sort()).toEqual(['phantora-shell-v1'])
  })

  it('removes the caches the app used under its previous name', async () => {
    network = () => html()
    const sw = boot()
    await sw.caches.set('parda-shell-v1', new FakeCache())
    await sw.caches.set('parda-assets-v1', new FakeCache())
    await sw.event('install')
    await sw.event('activate')
    expect([...sw.caches.keys()].sort()).toEqual(['phantora-shell-v1'])
  })
})
