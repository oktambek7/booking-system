/*
 * One-time move of browser storage from the old product name to Phantora, so a returning visitor keeps their language,
 * theme, saved offline tickets and profile overrides. Each old value is copied only when the new key is still empty,
 * then the old key is removed, so the move is safe to run on every start and never overwrites newer data.
 */
const LEGACY_PREFIX = 'parda_'
const NEXT_PREFIX = 'phantora_'
const LEGACY_SESSION_PREFIX = 'parda:'

function legacyKeys(store: Storage, prefix: string): string[] {
  const keys: string[] = []
  for (let i = 0; i < store.length; i += 1) {
    const key = store.key(i)
    if (key && key.startsWith(prefix)) keys.push(key)
  }
  return keys
}

export function migrateLegacyStorage(): void {
  try {
    for (const key of legacyKeys(localStorage, LEGACY_PREFIX)) {
      const next = NEXT_PREFIX + key.slice(LEGACY_PREFIX.length)
      const value = localStorage.getItem(key)
      if (value !== null && localStorage.getItem(next) === null) localStorage.setItem(next, value)
      localStorage.removeItem(key)
    }
    // The catalogue cache is only a speed-up: drop the old entries instead of copying them.
    for (const key of legacyKeys(sessionStorage, LEGACY_SESSION_PREFIX)) sessionStorage.removeItem(key)
  } catch { /* storage blocked or unavailable: the app falls back to its defaults */ }
}
