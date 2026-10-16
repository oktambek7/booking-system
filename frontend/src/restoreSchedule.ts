/*
 * When the app opens and cannot reach the API (a server that is waking up, restarting or briefly failing), it keeps
 * trying in the background instead of giving up. The wait grows from 2 s and is capped at 30 s; after RESTORE_ATTEMPTS
 * failed tries (about two minutes) the page says the server is not responding and offers a manual retry.
 */
export const RESTORE_ATTEMPTS = 6
const FIRST_DELAY_MS = 2000
const MAX_DELAY_MS = 30000

/** Wait before try number `attempt` (1 = the first retry). */
export function restoreDelay(attempt: number): number {
  return Math.min(MAX_DELAY_MS, FIRST_DELAY_MS * 2 ** Math.max(0, attempt - 1))
}
