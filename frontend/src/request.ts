const pause = (milliseconds: number) => new Promise(resolve => window.setTimeout(resolve, milliseconds))

/**
 * Render's free instances can wake from sleep between browser requests. Login
 * is safe to retry because it has no stateful side effects.
 */
export async function requestWithRetry(url: string, init: RequestInit, retries = 1): Promise<Response> {
  let lastError: unknown
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      return await fetch(url, init)
    } catch (error) {
      lastError = error
      if (attempt < retries) await pause(1000 * (attempt + 1))
    }
  }
  throw lastError
}

export function requestErrorMessage(error: unknown, fallback: string, networkMessage = 'Server bilan aloqa o‘rnatib bo‘lmadi. Bir oz kutib qayta urinib ko‘ring.'): string {
  if (error instanceof TypeError && error.message === 'Failed to fetch') {
    return networkMessage
  }
  if (error instanceof DOMException && error.name === 'AbortError') {
    return 'So‘rov vaqti tugadi. Qayta urinib ko‘ring.'
  }
  return error instanceof Error ? error.message : fallback
}
