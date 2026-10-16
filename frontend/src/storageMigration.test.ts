import { beforeEach, describe, expect, it, vi } from 'vitest'
import { migrateLegacyStorage } from './storageMigration'

class MemoryStorage {
  private data = new Map<string, string>()
  get length() { return this.data.size }
  key(index: number) { return [...this.data.keys()][index] ?? null }
  getItem(key: string) { return this.data.has(key) ? this.data.get(key)! : null }
  setItem(key: string, value: string) { this.data.set(key, String(value)) }
  removeItem(key: string) { this.data.delete(key) }
}

let local: MemoryStorage
let session: MemoryStorage

beforeEach(() => {
  local = new MemoryStorage()
  session = new MemoryStorage()
  vi.stubGlobal('localStorage', local)
  vi.stubGlobal('sessionStorage', session)
})

describe('migrateLegacyStorage', () => {
  it('moves old keys to the new prefix and removes the old ones', () => {
    local.setItem('parda_lang', 'ru')
    local.setItem('parda_theme', 'light')
    local.setItem('parda_offline_tickets', '{"userId":1}')
    local.setItem('parda_profile_override_7', '{"nickname":"A"}')
    migrateLegacyStorage()
    expect(local.getItem('phantora_lang')).toBe('ru')
    expect(local.getItem('phantora_theme')).toBe('light')
    expect(local.getItem('phantora_offline_tickets')).toBe('{"userId":1}')
    expect(local.getItem('phantora_profile_override_7')).toBe('{"nickname":"A"}')
    expect(local.getItem('parda_lang')).toBeNull()
    expect(local.getItem('parda_offline_tickets')).toBeNull()
  })

  it('never overwrites a value already stored under the new key', () => {
    local.setItem('phantora_lang', 'en')
    local.setItem('parda_lang', 'ru')
    migrateLegacyStorage()
    expect(local.getItem('phantora_lang')).toBe('en')
    expect(local.getItem('parda_lang')).toBeNull()
  })

  it('is safe to run twice and leaves unrelated keys alone', () => {
    local.setItem('parda_lang', 'ru')
    local.setItem('other', 'x')
    migrateLegacyStorage()
    migrateLegacyStorage()
    expect(local.getItem('phantora_lang')).toBe('ru')
    expect(local.getItem('other')).toBe('x')
  })

  it('drops the old catalogue cache from session storage', () => {
    session.setItem('parda:catalog:now_playing:v1', '{}')
    session.setItem('phantora:catalog:now_playing:v1', '{}')
    migrateLegacyStorage()
    expect(session.getItem('parda:catalog:now_playing:v1')).toBeNull()
    expect(session.getItem('phantora:catalog:now_playing:v1')).toBe('{}')
  })

  it('does not throw when storage is blocked', () => {
    vi.stubGlobal('localStorage', { get length(): number { throw new Error('blocked') } })
    expect(() => migrateLegacyStorage()).not.toThrow()
  })
})
