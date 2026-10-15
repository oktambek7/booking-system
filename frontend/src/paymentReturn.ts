/**
 * Where a customer lands after paying on a provider's hosted page (`/?payment=<reference>`). The provider's
 * signed webhook, not this browser, is what confirms the booking, and it can arrive a moment after the redirect,
 * so the app asks the server until the payment has settled.
 */
export type PaymentOutcome = 'paid' | 'refunded' | 'failed' | 'pending'
export type PaymentState = { status: string } | null

const PAID = new Set(['succeeded', 'succeeded_demo'])
const REFUNDED = new Set(['refunded', 'partially_refunded', 'refunded_demo', 'partially_refunded_demo'])
const OPEN = new Set(['awaiting_provider', 'awaiting_verification'])

export function outcomeOf(status: string): PaymentOutcome | null {
  if (OPEN.has(status)) return null
  if (PAID.has(status)) return 'paid'
  if (REFUNDED.has(status)) return 'refunded'     // e.g. paid after the hold lapsed, so the money was returned
  return 'failed'
}

type WaitOptions = { attempts?: number; intervalMs?: number; sleep?: (ms: number) => Promise<void> }

/** Poll `load` until the payment settles. A missing payment counts as failed; running out of tries as pending. */
export async function waitForPayment(load: () => Promise<PaymentState>, options: WaitOptions = {}): Promise<PaymentOutcome> {
  const { attempts = 15, intervalMs = 1500, sleep = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms)) } = options
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    let outcome: PaymentOutcome | null = null
    try {
      const state = await load()
      if (state === null) return 'failed'
      outcome = outcomeOf(state.status)
    } catch { /* a dropped connection is retried like any other "not settled yet" */ }
    if (outcome) return outcome
    if (attempt < attempts - 1) await sleep(intervalMs)
  }
  return 'pending'
}

/** The payment reference in the address, removed from it so a reload does not repeat the check. */
export function takePaymentReference(href: string): { reference: string | null; cleaned: string } {
  const url = new URL(href)
  const reference = url.searchParams.get('payment')
  url.searchParams.delete('payment')
  return { reference: reference && /^[\w-]{1,80}$/.test(reference) ? reference : null, cleaned: `${url.pathname}${url.search}${url.hash}` }
}
