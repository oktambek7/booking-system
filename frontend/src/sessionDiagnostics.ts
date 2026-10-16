/*
 * A short in-memory log of what the browser's session requests got back (health check, refresh, "who am I").
 * Nothing is stored or sent anywhere: it exists so that a failing sign-in restore can be read off the page
 * (open the site with ?diag=1) instead of guessed at. Tokens and cookies are never recorded.
 */
export type SessionStep = { at: string; step: string; status: string; detail: string }

const MAX_STEPS = 30
const steps: SessionStep[] = []

export function recordSessionStep(step: string, status: number | string, detail = ''): void {
  steps.push({ at: new Date().toISOString().slice(11, 19), step, status: String(status), detail: detail.slice(0, 160) })
  if (steps.length > MAX_STEPS) steps.shift()
}

export function getSessionSteps(): SessionStep[] {
  return steps.slice()
}

export function resetSessionStepsForTests(): void {
  steps.length = 0
}
