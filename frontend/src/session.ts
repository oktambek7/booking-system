/**
 * Browser session handling for the API.
 *
 * The access token lives only in memory (never in localStorage, so injected script cannot read a
 * long-lived credential). The refresh token is an httpOnly cookie the browser manages; this module
 * trades it for a fresh access token shortly before the old one expires, or when the API answers 401.
 */
import { recordSessionStep } from './sessionDiagnostics'

type TokenListener = (token: string) => void

/** A session request the API answered with an error (as opposed to not answering at all). */
export class SessionRequestError extends Error {
  readonly status: number
  readonly retryAfterMs: number | undefined
  constructor(message: string, status: number, retryAfterMs?: number) {
    super(message)
    this.status = status
    this.retryAfterMs = retryAfterMs
  }
}

/** How long the server asked us to wait (Retry-After on a 429/503), or 0. */
export function retryAfterMs(error: unknown): number {
  return error instanceof SessionRequestError ? error.retryAfterMs ?? 0 : 0
}

async function errorDetail(response: Response): Promise<string> {
  try {
    const body = await response.clone().json() as { detail?: unknown }
    return typeof body.detail === 'string' ? body.detail : ''
  } catch { return '' }
}

function retryAfterOf(response: Response): number | undefined {
  const seconds = Number(response.headers.get('Retry-After'))
  return Number.isFinite(seconds) && seconds > 0 ? Math.min(seconds, 300) * 1000 : undefined
}

let apiBase = ''
let accessToken = ''
let refreshInFlight: Promise<string> | null = null
let refreshTimer: ReturnType<typeof setTimeout> | undefined
const tokenListeners = new Set<TokenListener>()
const expiredListeners = new Set<() => void>()

/** Seconds before expiry at which the token is refreshed in the background. */
const REFRESH_MARGIN_SECONDS = 60
const MIN_REFRESH_DELAY_SECONDS = 30

export function configureSession(base: string): void {
  apiBase = base.replace(/\/$/, '')
}

export function getAccessToken(): string {
  return accessToken
}

/** Store a freshly issued access token and schedule its background refresh. */
export function setAccessToken(token: string, expiresInSeconds?: number): void {
  accessToken = token
  clearTimeout(refreshTimer)
  if (token && expiresInSeconds) {
    const delay = Math.max(MIN_REFRESH_DELAY_SECONDS, expiresInSeconds - REFRESH_MARGIN_SECONDS)
    refreshTimer = setTimeout(() => { void refreshAccessToken().catch(() => undefined) }, delay * 1000)
  }
  tokenListeners.forEach((listener) => listener(token))
}

export function onTokenChange(listener: TokenListener): () => void {
  tokenListeners.add(listener)
  return () => { tokenListeners.delete(listener) }
}

/** Called when the server says the session is over (refresh cookie missing, expired or revoked). */
export function onSessionExpired(listener: () => void): () => void {
  expiredListeners.add(listener)
  return () => { expiredListeners.delete(listener) }
}

/**
 * Trade the refresh cookie for a new access token. Concurrent callers share one request, so a burst of
 * 401s causes one refresh. Resolves to '' when there is no valid session; rejects when the API could not
 * be reached (the session may still be fine, so callers must not sign the user out).
 */
export function refreshAccessToken(): Promise<string> {
  refreshInFlight ??= requestRefresh().finally(() => { refreshInFlight = null })
  return refreshInFlight
}

async function requestRefresh(): Promise<string> {
  let response: Response
  try {
    response = await fetch(`${apiBase}/api/auth/refresh`, { method: 'POST', credentials: 'include' })
  } catch (error) {
    recordSessionStep('refresh', 'no answer', error instanceof Error ? error.message : String(error))
    throw error
  }
  if (!response.ok) recordSessionStep('refresh', response.status, await errorDetail(response))
  else recordSessionStep('refresh', response.status, 'ok')
  if (response.status === 401 || response.status === 403) {
    setAccessToken('')
    return ''
  }
  if (!response.ok) throw new SessionRequestError(`Session refresh failed (${response.status})`, response.status, retryAfterOf(response))
  const body = await response.json() as { access_token: string; expires_in?: number }
  setAccessToken(body.access_token, body.expires_in)
  return body.access_token
}

function bearerOf(headers: HeadersInit | undefined): string | null {
  if (!headers) return null
  const value = headers instanceof Headers ? headers.get('Authorization')
    : Array.isArray(headers) ? headers.find(([key]) => key.toLowerCase() === 'authorization')?.[1]
    : Object.entries(headers).find(([key]) => key.toLowerCase() === 'authorization')?.[1]
  return value?.startsWith('Bearer ') ? value.slice(7) : null
}

function withBearer(headers: HeadersInit | undefined, token: string): Headers {
  const next = new Headers(headers)
  next.set('Authorization', `Bearer ${token}`)
  return next
}

/**
 * Drop-in replacement for fetch() for API calls. A request carrying a bearer token always goes out with the
 * newest token, and one that still comes back 401 is retried once after a silent refresh.
 */
export async function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const sent = bearerOf(init.headers)
  if (sent === null) return fetch(input, init)
  const first = await fetch(input, accessToken && accessToken !== sent ? { ...init, headers: withBearer(init.headers, accessToken) } : init)
  if (first.status !== 401) return first
  let fresh: string
  try {
    fresh = await refreshAccessToken()
  } catch {
    return first                       // API unreachable: keep the session, let the caller report the error
  }
  if (!fresh) {
    expiredListeners.forEach((listener) => listener())
    return first
  }
  return fetch(input, { ...init, headers: withBearer(init.headers, fresh) })
}

const HEALTH_TIMEOUT_MS = 8000

/**
 * Reject unless the API answers its health check. Unlike a refresh, a health check changes nothing, so it is safe
 * to repeat against a server that is asleep, restarting or being deployed.
 */
async function assertApiHealthy(): Promise<void> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS)
  try {
    const response = await fetch(`${apiBase}/health`, { cache: 'no-store', signal: controller.signal })
    recordSessionStep('health', response.status)
    // A host that has no health route (404/405) is not "down": carry on and let the refresh decide.
    if (!response.ok && response.status !== 404 && response.status !== 405) {
      throw new SessionRequestError(`The API is not ready (${response.status})`, response.status, retryAfterOf(response))
    }
  } catch (error) {
    if (!(error instanceof SessionRequestError)) recordSessionStep('health', 'no answer', error instanceof Error ? error.message : String(error))
    throw error
  } finally {
    clearTimeout(timer)
  }
}

/**
 * Restore a signed-in session when the page loads: the refresh cookie either yields an access token or
 * there is no session. The API must answer a health check first. A refresh rotates the cookie on the server, so
 * sending one to a server that cannot reply could rotate it while the answer is lost, and the browser would be
 * left holding a retired cookie. Rejects (without touching the cookie) when the API cannot be reached; the caller
 * retries later.
 */
export async function bootSession(options: { skipHealthCheck?: boolean } = {}): Promise<string> {
  try { localStorage.removeItem('parda_token') } catch { /* storage unavailable: nothing to clean */ }
  // After several failed health checks the check itself may be what is wrong, so let the refresh try anyway.
  if (!options.skipHealthCheck) await assertApiHealthy()
  return refreshAccessToken()
}

/** Sign this browser out: end the server session (best effort) and forget the in-memory token. */
export async function endSession(): Promise<void> {
  clearTimeout(refreshTimer)
  accessToken = ''
  try {
    await fetch(`${apiBase}/api/auth/logout`, { method: 'POST', credentials: 'include' })
  } catch { /* offline: the cookie expires on its own and the token is already gone */ }
  tokenListeners.forEach((listener) => listener(''))
}

/** For tests: forget all module state. */
export function resetSessionForTests(): void {
  clearTimeout(refreshTimer)
  accessToken = ''
  apiBase = ''
  refreshInFlight = null
  tokenListeners.clear()
  expiredListeners.clear()
}
