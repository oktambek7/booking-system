// Fails the build if the deployed security headers weaken or the built page needs inline script.
// Runs in CI after `npm run build` (see .github/workflows/ci.yml): node scripts/check-headers.mjs
import fs from 'node:fs'

const problems = []
const config = JSON.parse(fs.readFileSync(new URL('../vercel.json', import.meta.url), 'utf8'))
const all = config.headers.find((rule) => rule.source === '/(.*)')
const header = (name) => all?.headers.find((h) => h.key.toLowerCase() === name.toLowerCase())?.value
const need = (condition, message) => { if (!condition) problems.push(message) }

const csp = header('Content-Security-Policy') ?? ''
const directives = Object.fromEntries(csp.split(';').map((d) => d.trim()).filter(Boolean).map((d) => {
  const [name, ...values] = d.split(/\s+/)
  return [name, values]
}))
need(csp, 'Content-Security-Policy is missing')
need(JSON.stringify(directives['script-src']) === '["\'self\'"]', "script-src must be exactly 'self' (no inline or eval)")
need(!/unsafe-eval|strict-dynamic/.test(csp), "CSP must not allow 'unsafe-eval'")
need(directives['default-src']?.includes("'self'"), "default-src must be 'self'")
need(directives['object-src']?.includes("'none'"), "object-src must be 'none'")
need(directives['frame-ancestors']?.includes("'none'"), "frame-ancestors must be 'none'")
need(directives['base-uri']?.includes("'self'"), "base-uri must be 'self'")
need(directives['form-action']?.includes("'self'"), "form-action must be 'self'")
need(!(directives['connect-src'] ?? []).some((v) => v === '*' || v === 'https:'), 'connect-src must not allow every origin')
need(/max-age=\d{7,}/.test(header('Strict-Transport-Security') ?? ''), 'Strict-Transport-Security needs a long max-age')
need(header('X-Content-Type-Options') === 'nosniff', 'X-Content-Type-Options must be nosniff')
need(header('X-Frame-Options') === 'DENY', 'X-Frame-Options must be DENY')
need(Boolean(header('Referrer-Policy')), 'Referrer-Policy is missing')
need(/geolocation=\(self\)/.test(header('Permissions-Policy') ?? ''), 'Permissions-Policy must scope geolocation to self')
need(/camera=\(self\)/.test(header('Permissions-Policy') ?? ''), 'Permissions-Policy must allow the camera for our own pages only (ticket scanner)')
need(/microphone=\(\)/.test(header('Permissions-Policy') ?? ''), 'Permissions-Policy must keep the microphone disabled')

const worker = config.headers.find((rule) => rule.source === '/sw.js')
need(/max-age=0|no-cache|no-store/.test(worker?.headers.find((h) => h.key.toLowerCase() === 'cache-control')?.value ?? ''), '/sw.js must be served with Cache-Control that forces revalidation')
need(directives['worker-src']?.includes("'self'"), "worker-src must allow 'self' for the service worker")
need(directives['manifest-src']?.includes("'self'"), "manifest-src must allow 'self'")

const publicDir = new URL('../public/', import.meta.url)
const manifestFile = new URL('manifest.webmanifest', publicDir)
if (!fs.existsSync(manifestFile)) problems.push('public/manifest.webmanifest is missing')
else {
  const manifest = JSON.parse(fs.readFileSync(manifestFile, 'utf8'))
  need(manifest.name && manifest.short_name && manifest.start_url === '/' && manifest.display === 'standalone', 'manifest needs name, short_name, start_url "/" and display "standalone"')
  const sizes = (manifest.icons ?? []).map((icon) => icon.sizes)
  need(sizes.includes('192x192') && sizes.includes('512x512'), 'manifest needs 192x192 and 512x512 icons')
  need((manifest.icons ?? []).some((icon) => icon.purpose === 'maskable'), 'manifest needs a maskable icon')
  for (const icon of manifest.icons ?? []) need(fs.existsSync(new URL('.' + icon.src, publicDir)), `manifest icon ${icon.src} does not exist in public/`)
}
need(fs.existsSync(new URL('sw.js', publicDir)), 'public/sw.js is missing')

const dist = new URL('../dist/index.html', import.meta.url)
if (fs.existsSync(dist)) {
  const html = fs.readFileSync(dist, 'utf8')
  const inline = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)].filter(([, attrs, body]) => !/\bsrc=/.test(attrs) && body.trim())
  need(inline.length === 0, 'dist/index.html contains an inline <script>, which the CSP blocks')
  need(!/\son[a-z]+\s*=/i.test(html), 'dist/index.html contains inline event handlers, which the CSP blocks')
} else {
  console.warn('dist/index.html not found - skipping the built-page checks (run npm run build first)')
}

if (problems.length) {
  console.error('Security header check failed:\n - ' + problems.join('\n - '))
  process.exit(1)
}
console.log('Security headers OK')
