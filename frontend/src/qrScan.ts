/** Pure helpers for the operator's camera scanner (kept separate so they can be unit-tested without a camera). */

const TICKET_CODE = /\bPRD-[A-Z0-9]{8}\b/i

/**
 * The e-ticket QR carries the ticket code itself, but a printed or forwarded ticket may wrap it in other text,
 * so the code is searched for rather than expected to be the whole payload. Returns null for anything else
 * (another QR code in view, a loyalty card, a phone number) so it is never sent to the check-in endpoint.
 */
export function parseTicketCode(payload: string): string | null {
  const match = TICKET_CODE.exec(payload)
  return match ? match[0].toUpperCase() : null
}

/**
 * A QR code stays in front of the camera for many frames, so "have I seen this?" is about presence, not time:
 * a ticket is reported once when it comes into view, and only again after it has left the frame for `absentMs`.
 * (A timer would resubmit a ticket the operator is still holding still, and the repeat's "already checked in"
 * error would replace the success message.) Brief decode dropouts while the code is visible do not count as leaving.
 *
 * Call `accept` for every analysed frame with the code found, or null when none was.
 */
export function createPresenceGate(absentMs: number, now: () => number = () => Date.now()) {
  let current: string | null = null
  let lastSeen = 0
  return {
    accept(code: string | null): boolean {
      const time = now()
      if (code === null) {
        if (current !== null && time - lastSeen >= absentMs) current = null
        return false
      }
      const isNew = code !== current
      current = code
      lastSeen = time
      return isNew
    },
  }
}
