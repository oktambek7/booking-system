import { useEffect, useRef } from 'react'

/** Poll this often when the live stream is unavailable (a proxy that will not hold it open, or a network blip). */
const FALLBACK_POLL_MS = 15_000

/**
 * Keep a seat map current while it is open. The API streams a small "this screening changed" event whenever a
 * seat is taken or released; each event triggers `refresh`, which refetches the seat list. If the stream drops,
 * the browser reconnects by itself and, until it does, the map refreshes slowly on a timer. Nothing is fetched
 * while the tab is hidden; the map catches up as soon as it is shown again.
 */
export function useLiveSeats(api: string, screeningId: number | undefined, refresh: () => void): void {
  const latestRefresh = useRef(refresh)
  latestRefresh.current = refresh

  useEffect(() => {
    if (!screeningId) return undefined
    let stale = false
    let poll: ReturnType<typeof setInterval> | undefined
    let opened = false
    const refreshNow = () => {
      if (document.hidden) { stale = true; return }
      stale = false
      latestRefresh.current()
    }
    const stopPolling = () => { clearInterval(poll); poll = undefined }
    const startPolling = () => { poll ??= setInterval(refreshNow, FALLBACK_POLL_MS) }
    const onVisible = () => { if (!document.hidden && stale) refreshNow() }
    document.addEventListener('visibilitychange', onVisible)

    let source: EventSource | undefined
    if (typeof EventSource === 'undefined') {
      startPolling()
    } else {
      source = new EventSource(`${api}/api/screenings/${screeningId}/seats/stream`)
      source.addEventListener('ready', () => {
        stopPolling()
        if (opened) refreshNow()          // a reconnect: anything may have changed while we were away
        opened = true
      })
      source.addEventListener('seats', refreshNow)
      source.addEventListener('error', startPolling)
    }
    return () => {
      document.removeEventListener('visibilitychange', onVisible)
      source?.close()
      stopPolling()
    }
  }, [api, screeningId])
}
