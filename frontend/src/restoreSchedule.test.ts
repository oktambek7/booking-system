import { describe, expect, it } from 'vitest'
import { RESTORE_ATTEMPTS, restoreDelay } from './restoreSchedule'

describe('restoreDelay', () => {
  it('starts at two seconds and doubles', () => {
    expect([1, 2, 3, 4].map(restoreDelay)).toEqual([2000, 4000, 8000, 16000])
  })

  it('never waits longer than thirty seconds', () => {
    expect(restoreDelay(5)).toBe(30000)
    expect(restoreDelay(50)).toBe(30000)
  })

  it('treats nonsense attempt numbers as the first retry', () => {
    expect(restoreDelay(0)).toBe(2000)
    expect(restoreDelay(-3)).toBe(2000)
  })

  it('gives the server about two minutes before the page says it is not responding', () => {
    const total = Array.from({ length: RESTORE_ATTEMPTS - 1 }, (_, i) => restoreDelay(i + 1)).reduce((a, b) => a + b, 0)
    expect(total).toBeGreaterThanOrEqual(60000)
    expect(total).toBeLessThanOrEqual(120000)
  })
})
