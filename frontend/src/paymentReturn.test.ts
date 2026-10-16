import { describe, expect, it, vi } from 'vitest'
import { outcomeOf, takePaymentReference, waitForPayment } from './paymentReturn'

const instant = () => Promise.resolve()

describe('outcomeOf', () => {
  it('maps payment statuses to what the customer should be told', () => {
    expect(outcomeOf('succeeded')).toBe('paid')
    expect(outcomeOf('succeeded_demo')).toBe('paid')
    expect(outcomeOf('refunded')).toBe('refunded')
    expect(outcomeOf('partially_refunded')).toBe('refunded')
    for (const status of ['failed', 'amount_mismatch', 'paid_unfulfilled', 'expired']) expect(outcomeOf(status)).toBe('failed')
    expect(outcomeOf('awaiting_provider')).toBeNull()
  })
})

describe('waitForPayment', () => {
  it('keeps asking until the webhook has arrived', async () => {
    const answers = [{ status: 'awaiting_provider' }, { status: 'awaiting_provider' }, { status: 'succeeded' }]
    const load = vi.fn(async () => answers.shift() ?? null)
    expect(await waitForPayment(load, { sleep: instant })).toBe('paid')
    expect(load).toHaveBeenCalledTimes(3)
  })

  it('reports failure straight away', async () => {
    expect(await waitForPayment(async () => ({ status: 'failed' }), { sleep: instant })).toBe('failed')
  })

  it('treats an unknown payment as failed', async () => {
    expect(await waitForPayment(async () => null, { sleep: instant })).toBe('failed')
  })

  it('gives up as pending when the webhook never comes, without sleeping after the last try', async () => {
    const sleep = vi.fn(instant)
    const load = vi.fn(async () => ({ status: 'awaiting_provider' }))
    expect(await waitForPayment(load, { attempts: 4, sleep })).toBe('pending')
    expect(load).toHaveBeenCalledTimes(4)
    expect(sleep).toHaveBeenCalledTimes(3)
  })

  it('survives network errors and keeps trying', async () => {
    let calls = 0
    const load = async () => { calls += 1; if (calls < 3) throw new Error('offline'); return { status: 'succeeded' } }
    expect(await waitForPayment(load, { sleep: instant })).toBe('paid')
    expect(calls).toBe(3)
  })
})

describe('takePaymentReference', () => {
  it('returns the reference and an address without it', () => {
    expect(takePaymentReference('https://phantora.example/?payment=abc_DEF-123&panel=bookings#top'))
      .toEqual({ reference: 'abc_DEF-123', cleaned: '/?panel=bookings#top' })
  })

  it('ignores a missing or suspicious reference', () => {
    expect(takePaymentReference('https://phantora.example/').reference).toBeNull()
    expect(takePaymentReference('https://phantora.example/?payment=../../x').reference).toBeNull()
    expect(takePaymentReference('https://phantora.example/?payment=' + 'a'.repeat(81)).reference).toBeNull()
  })
})
