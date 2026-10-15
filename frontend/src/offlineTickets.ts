/**
 * An offline ticket wallet: the customer's upcoming confirmed tickets, kept in localStorage so the QR code can be
 * shown at the cinema door without a connection. Only what the door needs is stored (film, hall, time, seats, the
 * ticket code); no e-mail, name, payment or booking history. It is wiped on sign-out, when the session ends, and when
 * the account is deleted, and entries drop out once the screening is over.
 */
const KEY = 'parda_offline_tickets'
const MAX_TICKETS = 20
const GRACE_MS = 3 * 60 * 60 * 1000          // a ticket stays useful until a few hours after the film ends

export type OfflineTicket = {
  id: number
  ticket_code: string
  movie_title: string
  cinema_name: string
  auditorium_name: string
  starts_at: string
  ends_at: string
  seats: string[]
}

type Candidate = Partial<OfflineTicket> & { status?: string; customer_id?: number }
export type Wallet = { userId: number | null; savedAt: string; tickets: OfflineTicket[] }

export function selectTickets(bookings: Candidate[], now: number = Date.now()): OfflineTicket[] {
  return bookings
    .filter((b): b is Candidate & OfflineTicket => b.status === 'confirmed' && Boolean(b.ticket_code) && typeof b.ends_at === 'string'
      && Date.parse(b.ends_at) + GRACE_MS > now)
    .map(({ id, ticket_code, movie_title, cinema_name, auditorium_name, starts_at, ends_at, seats }) =>
      ({ id, ticket_code, movie_title, cinema_name, auditorium_name, starts_at, ends_at, seats }))
    .sort((a, b) => Date.parse(a.starts_at) - Date.parse(b.starts_at))
    .slice(0, MAX_TICKETS)
}

/** Replace the wallet with the customer's current upcoming tickets (or empty it when there are none). */
export function saveTickets(bookings: Candidate[], now: number = Date.now()): void {
  try {
    const tickets = selectTickets(bookings, now)
    if (!tickets.length) { localStorage.removeItem(KEY); return }
    const userId = bookings.find(b => typeof b.customer_id === 'number')?.customer_id ?? null
    localStorage.setItem(KEY, JSON.stringify({ userId, savedAt: new Date(now).toISOString(), tickets } satisfies Wallet))
  } catch { /* storage full or unavailable: the wallet is a convenience, never a requirement */ }
}

/** The saved tickets that are still useful, or null when there are none. */
export function loadTickets(now: number = Date.now()): Wallet | null {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return null
    const wallet = JSON.parse(raw) as Wallet
    if (!Array.isArray(wallet.tickets)) return null
    const tickets = wallet.tickets.filter(t => t && typeof t.ticket_code === 'string' && Date.parse(t.ends_at) + GRACE_MS > now)
    return tickets.length ? { ...wallet, tickets } : null
  } catch { return null }
}

export function clearTickets(): void {
  try { localStorage.removeItem(KEY) } catch { /* nothing to clear */ }
}
