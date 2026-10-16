import { useEffect, useState } from 'react'
import { bootSession } from '../session'
import { getSessionSteps, type SessionStep } from '../sessionDiagnostics'

/** True when the page was opened with ?diag=1 (or ?diag): a hidden panel for finding out why a sign-in is not restored. */
export const diagnosticsRequested = (): boolean => new URLSearchParams(window.location.search).has('diag')

export default function SessionDiagnostics() {
  const [steps, setSteps] = useState<SessionStep[]>(getSessionSteps())
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    const timer = window.setInterval(() => setSteps(getSessionSteps()), 700)
    return () => window.clearInterval(timer)
  }, [])
  const page = {
    origin: window.location.origin,
    online: navigator.onLine,
    cookiesEnabled: navigator.cookieEnabled,
    serviceWorkerControlsPage: Boolean(navigator.serviceWorker?.controller),
    secureContext: window.isSecureContext,
    build: typeof __BUILD__ === 'string' ? __BUILD__ : 'unknown',
  }
  const report = JSON.stringify({ page, steps }, null, 2)
  return (
    <aside className="session-diagnostics" aria-label="Session diagnostics">
      <b>Session diagnostics</b>
      <pre>{JSON.stringify(page)}</pre>
      <ul>
        {steps.length === 0 && <li>No session requests yet.</li>}
        {steps.map((step, i) => <li key={i}><time>{step.at}</time> <b>{step.step}</b> → {step.status}{step.detail ? ` · ${step.detail}` : ''}</li>)}
      </ul>
      <div>
        <button type="button" onClick={() => { void bootSession({ skipHealthCheck: true }).catch(() => undefined).finally(() => setSteps(getSessionSteps())) }}>Check again</button>
        <button type="button" onClick={() => { void navigator.clipboard?.writeText(report).then(() => setCopied(true)).catch(() => undefined) }}>{copied ? 'Copied' : 'Copy'}</button>
      </div>
    </aside>
  )
}
