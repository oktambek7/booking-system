/**
 * Save an API response as a file download. Authenticated downloads cannot be a plain link (the browser would not
 * send the bearer token), so the response is fetched, turned into a temporary object URL and "clicked".
 * The name comes from the server's Content-Disposition header when it has one.
 */
export async function saveResponse(response: Response, fallbackName: string): Promise<void> {
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = (/filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') ?? '') ?? [])[1] ?? fallbackName
  document.body.append(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}
