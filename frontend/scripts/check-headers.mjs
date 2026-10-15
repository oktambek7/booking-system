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
