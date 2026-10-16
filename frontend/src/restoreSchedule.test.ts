import { describe, expect, it } from 'vitest'
import { RESTORE_PLACEHOLDER_ATTEMPTS, restoreDelay } from './restoreSchedule'

describe('restoreDelay', () => {
  it('starts at two seconds and doubles', () => {
    expect([1, 2, 3, 4].map(restoreDelay)).toEqual([2000, 4000, 8000, 16000])
  })

  it('never waits longer than thirty seconds, however many tries have failed', () => {
    expect(restoreDelay(5)).toBe(30000)
    expect(restoreDelay(50)).toBe(30000)
    expect(restoreDelay(5000)).toBe(30000)
  })

  it('treats nonsense attempt numbers as the first retry', () => {
    expect(restoreDelay(0)).toBe(2000)
    expect(restoreDelay(-3)).toBe(2000)
  })

  it('shows the neutral placeholder only for a short while', () => {
    const quiet = Array.from({ length: RESTORE_PLACEHOLDER_ATTEMPTS - 1 }, (_, i) => restoreDelay(i + 1)).reduce((a, b) => a + b, 0)
    expect(quiet).toBeLessThanOrEqual(10000)
  })
})
