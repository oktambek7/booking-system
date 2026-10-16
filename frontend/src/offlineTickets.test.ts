import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearTickets, loadTickets, saveTickets, selectTickets } from './offlineTickets'

const NOW = Date.parse('2026-10-16T12:00:00Z')
const hours = (n: number) => new Date(NOW + n * 3_600_000).toISOString()
const booking = (over: Record<string, unknown> = {}) => ({
  id: 1, status: 'confirmed', customer_id: 7, ticket_code: 'PRD-AAAAAAAA', movie_title: 'Film', cinema_name: 'Cinema', auditorium_name: 'Hall 1',
  starts_at: hours(5), ends_at: hours(7), seats: ['A1'], ...over,
})

let store: Record<string, string>
beforeEach(() => {
  store = {}
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => (key in store ? store[key] : null),
    setItem: (key: string, value: string) => { store[key] = value },
    removeItem: (key: string) => { delete store[key] },
  })
})
afterEach(() => vi.unstubAllGlobals())

describe('selectTickets', () => {
  it('keeps only upcoming confirmed tickets that have a code', () => {
    const chosen = selectTickets([
      booking({ id: 1 }), booking({ id: 2, status: 'pending' }), booking({ id: 3, status: 'cancelled' }),
      booking({ id: 4, ticket_code: null }), booking({ id: 5, starts_at: hours(-30), ends_at: hours(-28) }),
    ], NOW)
    expect(chosen.map(t => t.id)).toEqual([1])
  })

  it('keeps a ticket for a few hours after the film ends, then drops it', () => {
    expect(selectTickets([booking({ ends_at: hours(-2) })], NOW)).toHaveLength(1)
    expect(selectTickets([booking({ ends_at: hours(-4) })], NOW)).toHaveLength(0)
  })

  it('stores only what the door needs', () => {
    const [ticket] = selectTickets([booking({ customer_email: 'x@example.com', total_price: 30000, refund_amount: 0, promotion_code: 'SECRET' })], NOW)
    expect(Object.keys(ticket).sort()).toEqual(['auditorium_name', 'cinema_name', 'ends_at', 'id', 'movie_title', 'seats', 'starts_at', 'ticket_code'])
  })

  it('orders by start time and caps the list', () => {
    const many = Array.from({ length: 30 }, (_, i) => booking({ id: i + 1, starts_at: hours(30 - i), ends_at: hours(32 - i) }))
    const chosen = selectTickets(many, NOW)
    expect(chosen).toHaveLength(20)
    expect(chosen[0].id).toBe(30)
    expect(chosen.map(t => Date.parse(t.starts_at))).toEqual([...chosen.map(t => Date.parse(t.starts_at))].sort((a, b) => a - b))
  })
})

describe('wallet storage', () => {
  it('round-trips the tickets', () => {
    saveTickets([booking()], NOW)
    const wallet = loadTickets(NOW)
    expect(wallet?.userId).toBe(7)
    expect(wallet?.tickets.map(t => t.ticket_code)).toEqual(['PRD-AAAAAAAA'])
  })

  it('is emptied when the customer has no upcoming tickets any more', () => {
    saveTickets([booking()], NOW)
    saveTickets([booking({ status: 'cancelled' })], NOW)
    expect(loadTickets(NOW)).toBeNull()
  })

  it('is wiped on sign-out', () => {
    saveTickets([booking()], NOW)
    clearTickets()
    expect(loadTickets(NOW)).toBeNull()
    expect(Object.keys(store)).toHaveLength(0)
  })

  it('does not return tickets whose screening is over', () => {
    saveTickets([booking()], NOW)
    expect(loadTickets(NOW + 12 * 3_600_000)).toBeNull()
  })

  it('survives corrupt or hostile stored data', () => {
    for (const junk of ['not json', '{"tickets":"nope"}', 'null', '{"tickets":[null,{"ticket_code":5}]}']) {
      store.phantora_offline_tickets = junk
      expect(loadTickets(NOW)).toBeNull()
    }
  })

  it('never throws when storage is unavailable', () => {
    vi.stubGlobal('localStorage', { getItem: () => { throw new Error('blocked') }, setItem: () => { throw new Error('blocked') }, removeItem: () => { throw new Error('blocked') } })
    expect(() => saveTickets([booking()], NOW)).not.toThrow()
    expect(loadTickets(NOW)).toBeNull()
    expect(() => clearTickets()).not.toThrow()
  })
})
