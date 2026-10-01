import { useEffect, useState } from 'react'

export const FALLBACK_RESEND_COOLDOWN_SECONDS = 120

export function useResendCountdown() {
  const [until, setUntil] = useState(0)
  const [now, setNow] = useState(Date.now())
  const secondsLeft = Math.max(0, Math.ceil((until - now) / 1000))

  useEffect(() => {
    if (!secondsLeft) return
    const timer = window.setInterval(() => setNow(Date.now()), 1_000)
    return () => window.clearInterval(timer)
  }, [secondsLeft])

  return {
    secondsLeft,
    start: (availableAt?: string | null) => {
      const current = Date.now()
      const parsed = availableAt ? Date.parse(availableAt) : NaN
      // Start every new request at a clear, full two minutes. The API remains
      // authoritative, while this protects the UI from clock and network drift.
      const serverSeconds = Number.isFinite(parsed) ? Math.ceil((parsed - current) / 1_000) : 0
      const duration = Math.max(FALLBACK_RESEND_COOLDOWN_SECONDS, serverSeconds)
      setNow(current)
      setUntil(current + duration * 1_000)
    },
    clear: () => setUntil(0),
    label: `${Math.floor(secondsLeft / 60)}:${String(secondsLeft % 60).padStart(2, '0')}`,
  }
}
