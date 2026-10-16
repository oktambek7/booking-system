import { describe, expect, it } from 'vitest'
import { createPresenceGate, parseTicketCode } from './qrScan'

describe('parseTicketCode', () => {
  it('reads a bare ticket code', () => {
    expect(parseTicketCode('PRD-ABCD2345')).toBe('PRD-ABCD2345')
  })

  it('normalises case and surrounding whitespace', () => {
    expect(parseTicketCode('  prd-abcd2345\n')).toBe('PRD-ABCD2345')
  })

  it('finds the code inside longer text or a link', () => {
    expect(parseTicketCode('Phantora ticket PRD-9XK4M2QP, row A')).toBe('PRD-9XK4M2QP')
    expect(parseTicketCode('https://phantora.example/t?code=PRD-9XK4M2QP&x=1')).toBe('PRD-9XK4M2QP')
  })

  it('refuses anything that is not a ticket code', () => {
    for (const other of ['', '12345', 'https://example.com', '+998901234567', 'PRD-SHORT', 'PRD-TOOLONGCODE1', 'XYZ-ABCD2345', 'PRD ABCD2345']) {
      expect(parseTicketCode(other), other).toBeNull()
    }
  })

  it('does not match a code embedded in a longer word', () => {
    expect(parseTicketCode('XPRD-ABCD2345')).toBeNull()
    expect(parseTicketCode('PRD-ABCD23456')).toBeNull()
  })
})

describe('createPresenceGate', () => {
  const frames = (gate: ReturnType<typeof createPresenceGate>, clock: { t: number }, code: string | null, count: number, step = 160) => {
    const accepted: boolean[] = []
    for (let i = 0; i < count; i += 1) { clock.t += step; accepted.push(gate.accept(code)) }
    return accepted
  }

  it('reports a ticket once, however long it stays in view', () => {
    const clock = { t: 0 }
    const gate = createPresenceGate(1200, () => clock.t)
    const accepted = frames(gate, clock, 'PRD-AAAAAAAA', 100)             // 16 seconds of the same code
    expect(accepted.filter(Boolean)).toHaveLength(1)
    expect(accepted[0]).toBe(true)
  })

  it('reports it again only after it has left the frame', () => {
    const clock = { t: 0 }
    const gate = createPresenceGate(1200, () => clock.t)
    expect(frames(gate, clock, 'PRD-AAAAAAAA', 3)[0]).toBe(true)
    frames(gate, clock, null, 10)                                           // 1.6 s with nothing in view
    expect(frames(gate, clock, 'PRD-AAAAAAAA', 2)[0]).toBe(true)
  })

  it('treats a short decode dropout as the same ticket, not a new one', () => {
    const clock = { t: 0 }
    const gate = createPresenceGate(1200, () => clock.t)
    gate.accept('PRD-AAAAAAAA')
    frames(gate, clock, null, 3)                                            // blur for ~0.5 s
    expect(frames(gate, clock, 'PRD-AAAAAAAA', 5).some(Boolean)).toBe(false)
  })

  it('accepts a different ticket straight away', () => {
    const clock = { t: 0 }
    const gate = createPresenceGate(1200, () => clock.t)
    gate.accept('PRD-AAAAAAAA')
    expect(frames(gate, clock, 'PRD-BBBBBBBB', 2)[0]).toBe(true)
  })

  it('never reports an empty frame', () => {
    const clock = { t: 0 }
    const gate = createPresenceGate(1200, () => clock.t)
    expect(frames(gate, clock, null, 20).some(Boolean)).toBe(false)
  })
})
