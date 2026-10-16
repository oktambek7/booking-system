/*
 * When the app opens and cannot reach the API (a server that is waking up, restarting or being deployed) it keeps
 * trying in the background until the session is restored; nothing is shown about it. The wait grows from 2 s and
 * is capped at 30 s. For the first few tries the header shows a neutral placeholder instead of "Sign in", so a
 * short outage does not look like being signed out.
 */
export const RESTORE_PLACEHOLDER_ATTEMPTS = 3
const FIRST_DELAY_MS = 2000
const MAX_DELAY_MS = 30000

/** Wait before try number `attempt` (1 = the first retry). */
export function restoreDelay(attempt: number): number {
  return Math.min(MAX_DELAY_MS, FIRST_DELAY_MS * 2 ** Math.min(10, Math.max(0, attempt - 1)))
}
