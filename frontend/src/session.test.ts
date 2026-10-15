import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  apiFetch, bootSession, configureSession, endSession, getAccessToken, onSessionExpired, onTokenChange,
  refreshAccessToken, resetSessionForTests, setAccessToken,
} from './session'

type Handler = (url: string, init?: RequestInit) => Response | Promise<Response>
const json = (status: number, body: unknown = {}) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const bearer = (init?: RequestInit) => new Headers(init?.headers).get('Authorization')

let calls: { url: string; init?: RequestInit }[]
function mockFetch(handler: Handler) {
  calls = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => { calls.push({ url, init }); return handler(url, init) }))
}
const refreshCalls = () => calls.filter((c) => c.url.endsWith('/api/auth/refresh')).length

beforeEach(() => { resetSessionForTests(); configureSession('https://site.example') })
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

describe('apiFetch', () => {
  it('passes successful responses through untouched', async () => {
    mockFetch(() => json(200, { ok: true }))
    const response = await apiFetch('/api/movies', { headers: { Authorization: 'Bearer abc' } })
    expect(response.status).toBe(200)
    expect(calls).toHaveLength(1)
  })

  it('refreshes once on 401 and retries with the new token', async () => {
    mockFetch((url, init) => {
      if (url.endsWith('/api/auth/refresh')) return json(200, { access_token: 'new-token', expires_in: 900 })
      return bearer(init) === 'Bearer new-token' ? json(200, { ok: true }) : json(401)
    })
    const seen: string[] = []
    onTokenChange((token) => seen.push(token))
    const response = await apiFetch('/api/bookings', { headers: { Authorization: 'Bearer old-token' } })
    expect(response.status).toBe(200)
    expect(refreshCalls()).toBe(1)
    expect(seen).toContain('new-token')
    expect(getAccessToken()).toBe('new-token')
  })

  it('sends the refresh with the cookie credentials', async () => {
    mockFetch((url) => (url.endsWith('/api/auth/refresh') ? json(200, { access_token: 't' }) : json(401)))
    await apiFetch('/api/bookings', { headers: { Authorization: 'Bearer x' } })
    const refresh = calls.find((c) => c.url.endsWith('/api/auth/refresh'))!
    expect(refresh.url).toBe('https://site.example/api/auth/refresh')
    expect(refresh.init).toMatchObject({ method: 'POST', credentials: 'include' })
  })

  it('shares one refresh between simultaneous 401s', async () => {
    mockFetch(async (url, init) => {
      if (url.endsWith('/api/auth/refresh')) { await new Promise((r) => setTimeout(r, 20)); return json(200, { access_token: 'fresh' }) }
      return bearer(init) === 'Bearer fresh' ? json(200) : json(401)
    })
    const requests = ['/a', '/b', '/c', '/d'].map((path) => apiFetch(path, { headers: { Authorization: 'Bearer stale' } }))
    const statuses = (await Promise.all(requests)).map((r) => r.status)
    expect(statuses).toEqual([200, 200, 200, 200])
    expect(refreshCalls()).toBe(1)
  })

  it('announces an ended session once the refresh is refused, and does not loop', async () => {
    mockFetch((url) => (url.endsWith('/api/auth/refresh') ? json(401) : json(401)))
    const expired = vi.fn()
    onSessionExpired(expired)
    const response = await apiFetch('/api/bookings', { headers: { Authorization: 'Bearer old' } })
    expect(response.status).toBe(401)
    expect(expired).toHaveBeenCalledTimes(1)
    expect(refreshCalls()).toBe(1)
    expect(calls).toHaveLength(2)                            // the request and the refresh: no retry
  })

  it('keeps the session when the API cannot be reached during a refresh', async () => {
    mockFetch((url) => { if (url.endsWith('/api/auth/refresh')) throw new TypeError('Failed to fetch'); return json(401) })
    const expired = vi.fn()
    onSessionExpired(expired)
    const response = await apiFetch('/api/bookings', { headers: { Authorization: 'Bearer old' } })
    expect(response.status).toBe(401)
    expect(expired).not.toHaveBeenCalled()
  })

  it('keeps the session when the refresh endpoint answers 5xx', async () => {
    mockFetch((url) => (url.endsWith('/api/auth/refresh') ? json(503) : json(401)))
    const expired = vi.fn()
    onSessionExpired(expired)
    await apiFetch('/api/bookings', { headers: { Authorization: 'Bearer old' } })
    expect(expired).not.toHaveBeenCalled()
  })

  it('does not try to refresh a failed sign-in (no bearer token)', async () => {
    mockFetch(() => json(401, { detail: 'Email or password is incorrect' }))
    const response = await apiFetch('/api/auth/login', { method: 'POST', body: '{}' })
    expect(response.status).toBe(401)
    expect(refreshCalls()).toBe(0)
  })

  it('sends the newest token instead of a stale one, avoiding a pointless 401', async () => {
    mockFetch((_url, init) => (bearer(init) === 'Bearer current' ? json(200) : json(401)))
    setAccessToken('current')
    const response = await apiFetch('/api/bookings', { headers: { Authorization: 'Bearer stale' } })
    expect(response.status).toBe(200)
    expect(calls).toHaveLength(1)
  })

  it('understands Headers objects and array headers too', async () => {
    mockFetch((url, init) => {
      if (url.endsWith('/api/auth/refresh')) return json(200, { access_token: 'n' })
      return bearer(init) === 'Bearer n' ? json(200) : json(401)
    })
    expect((await apiFetch('/x', { headers: new Headers({ authorization: 'Bearer o' }) })).status).toBe(200)
    expect((await apiFetch('/y', { headers: [['Authorization', 'Bearer o']] })).status).toBe(200)
  })
})

describe('refreshAccessToken', () => {
  it('resolves to an empty token when there is no session', async () => {
    mockFetch(() => json(401))
    expect(await refreshAccessToken()).toBe('')
  })

  it('refreshes in the background shortly before the token expires', async () => {
    vi.useFakeTimers()
    mockFetch(() => json(200, { access_token: 'next', expires_in: 900 }))
    setAccessToken('first', 900)
    expect(refreshCalls()).toBe(0)
    await vi.advanceTimersByTimeAsync(839_000)
    expect(refreshCalls()).toBe(0)
    await vi.advanceTimersByTimeAsync(2_000)               // 60 s before the 900 s expiry
    expect(refreshCalls()).toBe(1)
    expect(getAccessToken()).toBe('next')
  })
})

describe('bootSession', () => {
  it('discards the legacy localStorage token and restores the session from the cookie', async () => {
    const removed: string[] = []
    vi.stubGlobal('localStorage', { removeItem: (key: string) => removed.push(key) })
    mockFetch(() => json(200, { access_token: 'restored', expires_in: 900 }))
    expect(await bootSession()).toBe('restored')
    expect(removed).toContain('parda_token')
  })

  it('returns an empty token for a visitor who is not signed in', async () => {
    mockFetch(() => json(401))
    expect(await bootSession()).toBe('')
  })

  it('retries once after a network failure such as a cold start', async () => {
    vi.useFakeTimers()
    let attempt = 0
    mockFetch(() => { attempt += 1; if (attempt === 1) throw new TypeError('Failed to fetch'); return json(200, { access_token: 'late' }) })
    const booting = bootSession()
    await vi.advanceTimersByTimeAsync(1600)
    expect(await booting).toBe('late')
    expect(refreshCalls()).toBe(2)
  })
})

describe('endSession', () => {
  it('forgets the token, tells the server and notifies listeners', async () => {
    mockFetch(() => new Response(null, { status: 204 }))
    setAccessToken('live', 900)
    const seen: string[] = []
    onTokenChange((token) => seen.push(token))
    await endSession()
    expect(getAccessToken()).toBe('')
    expect(calls[0].url).toBe('https://site.example/api/auth/logout')
    expect(calls[0].init).toMatchObject({ method: 'POST', credentials: 'include' })
    expect(seen.at(-1)).toBe('')
  })

  it('still signs out locally when the server is unreachable', async () => {
    mockFetch(() => { throw new TypeError('Failed to fetch') })
    setAccessToken('live')
    await endSession()
    expect(getAccessToken()).toBe('')
  })
})
